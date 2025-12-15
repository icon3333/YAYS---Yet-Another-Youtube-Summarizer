#!/usr/bin/env python3
"""
YouTube Video Processing Engine
Main entry point for video summarization
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from time import sleep, time
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import core modules
from src.core.youtube import YouTubeClient
from src.core.transcript import TranscriptExtractor
from src.core.ai_summarizer import AISummarizer
from src.core.email_sender import EmailSender
from src.utils.log_cleanup import cleanup_old_logs
from src.core.constants import (
    STATUS_PENDING, STATUS_PROCESSING, STATUS_SUCCESS,
    STATUS_FETCHING_METADATA, STATUS_FETCHING_TRANSCRIPT, STATUS_GENERATING_SUMMARY,
    STATUS_SENDING_EMAIL,
    STATUS_FAILED_TRANSCRIPT, STATUS_FAILED_AI, STATUS_FAILED_EMAIL,
    RATE_LIMIT_DELAY
)

# Import managers
from src.managers.config_manager import ConfigManager
from src.managers.settings_manager import SettingsManager
from src.managers.database import VideoDatabase

# Import utilities
from src.utils.validators import is_valid_email


# Configure structured logging
def setup_logging():
    """Setup logging with rotation and formatting.

    - Console: only messages from the 'summarizer' logger
    - File: capture ALL module logs to help diagnose transcript issues
    """
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)

    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    # Create our app logger
    logger = logging.getLogger('summarizer')
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Console handler (only for summarizer logger)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler with rotation on ROOT to capture all module logs
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'summarizer.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    return logger


class VideoProcessor:
    """Main video processing orchestrator"""

    def __init__(self):
        """Initialize with config, credentials, and logging"""
        self.logger = setup_logging()

        # Check for concurrent runs using PID lock
        self.pid_lock_file = Path('data/.processor.pid')
        if not self._acquire_lock():
            self.logger.info("Another processor instance is already running. Exiting.")
            sys.exit(0)

        self.logger.info("="*60)
        self.logger.info("YouTube Summarizer v2.0 Initializing")
        self.logger.info("="*60)

        # Initialize database and managers
        self.db = VideoDatabase('data/videos.db')
        self.config_manager = ConfigManager(db_path='data/videos.db')
        self.settings_manager = SettingsManager(db_path='data/videos.db')

        # Load configuration from database
        channels, channel_names, channel_added_dates = self.config_manager.get_channels()
        self.logger.info(f"Loaded config: {len(channels)} channels")

        # Get settings from database
        all_settings = self.settings_manager.get_all_settings(mask_secrets=False)
        config_settings = self.config_manager.get_settings()

        # Load and validate credentials from database
        self.openai_key = all_settings.get('OPENAI_API_KEY', {}).get('value', '')
        self.target_email = all_settings.get('TARGET_EMAIL', {}).get('value', '')
        self.smtp_user = all_settings.get('SMTP_USER', {}).get('value', '')
        self.smtp_pass = all_settings.get('SMTP_PASS', {}).get('value', '')

        missing = []
        if not self.openai_key:
            missing.append('OPENAI_API_KEY')
        if not self.target_email:
            missing.append('TARGET_EMAIL')
        if not self.smtp_user:
            missing.append('SMTP_USER')
        if not self.smtp_pass:
            missing.append('SMTP_PASS')

        if missing:
            self.logger.error("Missing required settings in database:")
            for var in missing:
                self.logger.error(f"  - {var}")
            self.logger.error("Please configure settings using the web UI and restart")
            sys.exit(1)

        # Validate email format
        if not is_valid_email(self.target_email):
            self.logger.error(f"Invalid TARGET_EMAIL format: {self.target_email}")
            sys.exit(1)

        # Initialize components
        use_ytdlp = True  # Always use ytdlp

        self.youtube_client = YouTubeClient(use_ytdlp=use_ytdlp)

        # Configure transcript extractor with Supadata fallback if enabled
        enable_supadata_fallback = all_settings.get('ENABLE_SUPADATA_FALLBACK', {}).get('value', 'false') == 'true'
        supadata_api_key = all_settings.get('SUPADATA_API_KEY', {}).get('value', '')

        # Log the cascade configuration
        if enable_supadata_fallback and supadata_api_key:
            self.logger.info("Using 4-method cascade with Supadata.ai fallback enabled")
        else:
            self.logger.info("Using 3-method cascade (Supadata.ai fallback disabled)")

        self.transcript_extractor = TranscriptExtractor(
            provider='legacy',  # Always use cascade starting with legacy
            supadata_api_key=supadata_api_key if enable_supadata_fallback else None,
            cache=self.db
        )

        # Get model from database or use default
        openai_model = all_settings.get('OPENAI_MODEL', {}).get('value', 'gpt-4o-mini')
        self.summarizer = AISummarizer(self.openai_key, model=openai_model)
        self.email_sender = EmailSender(self.smtp_user, self.smtp_pass, self.target_email)

        # Store channels and settings for later use
        self.channels = channels
        self.channel_names = channel_names
        self.channel_added_dates = channel_added_dates
        self.config_settings = config_settings
        self.send_email = all_settings.get('SEND_EMAIL_SUMMARIES', {}).get('value', 'true').lower() == 'true'

        self.logger.info("Database initialized")

        # Initialize lock file for process heartbeat
        self.lock_file = Path('data/.processing.lock')
        self.last_heartbeat = time()
        self._update_heartbeat()

        # Statistics
        self.stats = {
            'videos_processed': 0,
            'videos_skipped': 0,
            'videos_failed': 0,
            'api_calls': 0,
            'api_errors': 0,
            'email_sent': 0,
            'email_failed': 0
        }

        self.logger.info("Initialization complete")

    def _update_heartbeat(self):
        """Update process heartbeat lock file with current timestamp"""
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(str(time()))
            self.last_heartbeat = time()
        except Exception as e:
            self.logger.warning(f"Failed to update heartbeat: {e}")

    def _is_processor_alive(self, threshold_seconds: int = 120) -> bool:
        """Check if another processor is actively running"""
        try:
            if not self.lock_file.exists():
                return False

            last_update = float(self.lock_file.read_text())
            age = time() - last_update
            return age < threshold_seconds
        except Exception:
            return False

    def _acquire_lock(self) -> bool:
        """
        Acquire PID-based lock to prevent concurrent runs.
        Returns True if lock acquired, False if another instance is running.
        """
        try:
            self.pid_lock_file.parent.mkdir(parents=True, exist_ok=True)

            # Check if lock file exists
            if self.pid_lock_file.exists():
                try:
                    old_pid = int(self.pid_lock_file.read_text().strip())

                    # Check if process with this PID is still running
                    import psutil
                    if psutil.pid_exists(old_pid):
                        try:
                            proc = psutil.Process(old_pid)
                            # Check if it's actually a Python process running our script
                            if 'python' in proc.name().lower():
                                return False  # Another instance is running
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    # Stale lock file, remove it
                    self.pid_lock_file.unlink()
                except (ValueError, FileNotFoundError, psutil.NoSuchProcess):
                    # Invalid or stale lock file, remove it
                    try:
                        self.pid_lock_file.unlink()
                    except FileNotFoundError:
                        pass

            # Write our PID to lock file
            import os
            self.pid_lock_file.write_text(str(os.getpid()))
            return True

        except Exception as e:
            # In Docker, stale locks are common on restart - just clear and proceed
            try:
                self.pid_lock_file.unlink()
                import os
                self.pid_lock_file.write_text(str(os.getpid()))
                return True
            except:
                self.logger.warning(f"Error acquiring lock: {e}")
                return False

    def _release_lock(self):
        """Release the PID lock file"""
        try:
            if self.pid_lock_file.exists():
                self.pid_lock_file.unlink()
        except Exception as e:
            self.logger.warning(f"Error releasing lock: {e}")

    def _should_process_video(self, video_upload_date: Optional[str], channel_added_at: Optional[str]) -> bool:
        """
        Determine if a video should be processed based on upload date vs channel added date.

        Args:
            video_upload_date: Video upload date in YYYY-MM-DD or YYYYMMDD format
            channel_added_at: Channel added timestamp in YYYY-MM-DD HH:MM:SS format

        Returns:
            True if video should be processed, False if it should be skipped
        """
        # If channel has no added_at (old channels), process all videos (backward compatibility)
        if not channel_added_at:
            return True

        # If video has no upload date, process it (can't determine if old/new)
        if not video_upload_date:
            return True

        try:
            # Parse channel added date (format: YYYY-MM-DD HH:MM:SS)
            # Extract just the date part for comparison
            channel_date_str = channel_added_at.split()[0]  # Get YYYY-MM-DD part
            channel_date = datetime.strptime(channel_date_str, '%Y-%m-%d').date()

            # Parse video upload date (could be YYYY-MM-DD or YYYYMMDD)
            if len(video_upload_date) == 8 and '-' not in video_upload_date:
                # Format: YYYYMMDD
                video_date = datetime.strptime(video_upload_date, '%Y%m%d').date()
            else:
                # Format: YYYY-MM-DD
                video_date = datetime.strptime(video_upload_date, '%Y-%m-%d').date()

            # Process video only if uploaded on or after channel was added
            return video_date >= channel_date

        except (ValueError, AttributeError, IndexError) as e:
            # If date parsing fails, process the video (fail-safe)
            self.logger.warning(f"Error parsing dates for filtering (will process video): {e}")
            return True

    def cleanup_stuck_videos(self):
        """
        Smart detection and cleanup of stuck videos using hybrid approach:
        1. Quick check: 2+ minutes without heartbeat
        2. Medium check: 5+ minutes in processing
        3. Absolute timeout: 10+ minutes regardless
        """
        try:
            # Get all videos currently in any processing state
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, title, processed_date, retry_count
                    FROM videos
                    WHERE processing_status IN (
                        'processing',
                        'fetching_metadata',
                        'fetching_transcript',
                        'generating_summary',
                        'sending_email'
                    )
                """)
                processing_videos = cursor.fetchall()

            if not processing_videos:
                return

            stuck_videos = []
            now = datetime.now()
            processor_alive = self._is_processor_alive()

            for row in processing_videos:
                video_id = row['id']
                title = row['title'][:50]
                processed_date = row['processed_date']
                retry_count = row['retry_count'] or 0

                if not processed_date:
                    continue

                # Calculate time in processing
                process_time = now - datetime.fromisoformat(processed_date)
                minutes_processing = process_time.total_seconds() / 60

                # Tier 1: Quick check (2+ minutes and no active processor)
                if minutes_processing > 2 and not processor_alive:
                    self.logger.warning(f"Stuck (no heartbeat): {title} ({minutes_processing:.1f} min)")
                    stuck_videos.append((video_id, retry_count))
                    continue

                # Tier 2: Medium check (5+ minutes regardless of heartbeat)
                if minutes_processing > 5:
                    self.logger.warning(f"Stuck (timeout): {title} ({minutes_processing:.1f} min)")
                    stuck_videos.append((video_id, retry_count))
                    continue

                # Tier 3: Absolute timeout (10+ minutes failsafe)
                if minutes_processing > 10:
                    self.logger.warning(f"Stuck (absolute): {title} ({minutes_processing:.1f} min)")
                    stuck_videos.append((video_id, retry_count))

            # Reset stuck videos
            if stuck_videos:
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    for video_id, retry_count in stuck_videos:
                        # Check retry limit
                        if retry_count >= 3:
                            # Mark as permanently failed after 3 attempts
                            cursor.execute("""
                                UPDATE videos
                                SET processing_status = 'failed_permanent',
                                    error_message = 'Max retries exceeded (3 attempts)'
                                WHERE id = ?
                            """, (video_id,))
                            self.logger.info(f"Marked as permanent failure: {video_id}")
                        else:
                            # Reset to pending for retry
                            cursor.execute("""
                                UPDATE videos
                                SET processing_status = 'pending',
                                    error_message = 'Reset from stuck processing state'
                                WHERE id = ?
                            """, (video_id,))
                            self.logger.info(f"Reset to pending: {video_id}")

                    conn.commit()

                self.logger.info(f"✅ Cleaned up {len(stuck_videos)} stuck videos")

        except Exception as e:
            self.logger.error(f"Error cleaning stuck videos: {e}")

    def process_video(self, video: Dict, channel_id: str, channel_name: str) -> bool:
        """
        Process a single video: extract transcript, summarize, save to DB, and optionally email
        Returns True if successful (summary generated and saved)
        """
        self.logger.info(f"   ▶️  {video['title'][:60]}...")

        # Update heartbeat to show we're actively processing
        self._update_heartbeat()

        # Mark as processing and set initial status
        if self.db.is_processed(video['id']):
            existing = self.db.get_video_by_id(video['id'])
            current_retry = existing.get('retry_count', 0)
            self.db.update_video_processing(
                video['id'],
                STATUS_FETCHING_METADATA,
                retry_count=current_retry + 1
            )
        else:
            self.db.add_video(
                video_id=video['id'],
                channel_id=channel_id,
                channel_name=channel_name,
                title=video['title'],
                processing_status=STATUS_FETCHING_METADATA
            )

        # STEP 1: Get enhanced metadata (if using yt-dlp)
        self.logger.info(f"      📊 Fetching metadata...")
        metadata = self.youtube_client.get_video_metadata(video['id'])
        if metadata:
            duration_seconds = metadata.get('duration', 0)
            view_count = metadata.get('view_count', 0)
            upload_date = metadata.get('upload_date_string', '')
            duration_str = metadata.get('duration_string', 'Unknown')
            title = metadata.get('title', video.get('title', f"Video {video['id']}"))
            metadata_channel_id = metadata.get('channel_id', channel_id)
            # Try 'channel' first, then 'uploader' as fallback for robustness
            metadata_channel_name = metadata.get('channel') or metadata.get('uploader') or channel_name

            self.logger.debug(f"      Metadata: {duration_str}, {metadata.get('view_count_string', 'Unknown views')}")

            # Update video dict with metadata
            video['duration_seconds'] = duration_seconds
            video['view_count'] = view_count
            video['upload_date'] = upload_date
            video['duration_string'] = duration_str
            video['title'] = title

            # Update database with fetched metadata (important for manually added videos)
            self.db.update_video_metadata(
                video_id=video['id'],
                title=title,
                channel_id=metadata_channel_id,
                channel_name=metadata_channel_name,
                duration_seconds=duration_seconds,
                view_count=view_count,
                upload_date=upload_date
            )
        else:
            # No metadata available (RSS fallback)
            video['duration_seconds'] = None
            video['view_count'] = None
            video['upload_date'] = None
            video['duration_string'] = 'Unknown'

        # STEP 2: Extract transcript using cascade
        self.db.update_video_processing(video['id'], STATUS_FETCHING_TRANSCRIPT)
        self.logger.info(f"      📝 Fetching transcript...")
        self._update_heartbeat()  # Keep heartbeat alive
        transcript, duration, transcript_source = self.transcript_extractor.get_transcript_cascade(video['id'])
        if not transcript:
            self.logger.info(f"      ❌ No transcript available")
            self.db.update_video_processing(
                video['id'],
                status=STATUS_FAILED_TRANSCRIPT,
                error_message='Transcript not available for this video'
            )
            self.stats['videos_skipped'] += 1
            return False

        # Use metadata duration if available, otherwise use transcript duration
        if not video.get('duration_string') or video['duration_string'] == 'Unknown':
            video['duration_string'] = duration or 'Unknown'

        # STEP 3: Generate AI summary
        self.db.update_video_processing(video['id'], STATUS_GENERATING_SUMMARY)
        self.logger.info(f"      🤖 Generating AI summary...")
        use_summary_length = self.config_settings.get('USE_SUMMARY_LENGTH', 'false') == 'true'
        max_tokens = int(self.config_settings.get('SUMMARY_LENGTH', '500')) if use_summary_length else None
        prompt_template = self.config_manager.get_prompt()
        self._update_heartbeat()  # Keep heartbeat alive
        summary = self.summarizer.summarize_with_retry(
            video=video,
            transcript=transcript,
            duration=video['duration_string'],
            prompt_template=prompt_template,
            max_tokens=max_tokens
        )

        if not summary:
            self.logger.info(f"      ❌ AI summarization failed")
            self.db.update_video_processing(
                video['id'],
                status=STATUS_FAILED_AI,
                error_message='Failed to generate summary using OpenAI API'
            )
            self.stats['videos_failed'] += 1
            self.stats['api_errors'] += 1
            return False

        self.stats['api_calls'] += 1

        # STEP 4: Save summary to database (but not final yet - may need to send email)
        self.db.update_video_processing(
            video['id'],
            status=STATUS_SUCCESS,
            summary_text=summary,
            summary_length=len(summary),
            transcript_source=transcript_source
        )
        self.logger.info(f"      ✅ Summary generated ({len(summary)} chars)")

        # STEP 5: Optionally send email
        if self.send_email:
            # Update status to show we're sending email
            self.db.update_video_processing(video['id'], STATUS_SENDING_EMAIL)
            self.logger.info(f"      📧 Sending email...")
            self._update_heartbeat()  # Keep heartbeat alive

            if self.email_sender.send_email(video, summary, channel_name):
                # Email sent successfully - mark as final success
                self.db.update_video_processing(video['id'], status=STATUS_SUCCESS, email_sent=True)
                self.stats['email_sent'] += 1
                self.logger.info(f"      ✅ Email sent successfully")
            else:
                # Email failed but summary is saved - mark as failed_email
                self.db.update_video_processing(
                    video['id'],
                    status=STATUS_FAILED_EMAIL,
                    error_message='Summary generated but email delivery failed',
                    email_sent=False
                )
                self.stats['email_failed'] += 1
                self.logger.warning(f"      ❌ Email failed (summary saved)")
        else:
            # Email disabled - mark as success since summary is saved
            self.logger.info(f"      📝 Email disabled (summary saved only)")
            self.db.update_video_processing(video['id'], status=STATUS_SUCCESS, email_sent=False)

        # Statistics
        self.stats['videos_processed'] += 1

        # Rate limiting
        sleep(RATE_LIMIT_DELAY)
        return True

    def run(self):
        """Main processing loop"""
        self.logger.info("")
        self.logger.info("="*60)
        self.logger.info(f"Starting processing run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("="*60)

        # Clean up any stuck videos from previous runs
        self.logger.info("🔍 Checking for stuck videos...")
        self.cleanup_stuck_videos()

        # Clean up old log files based on retention setting
        try:
            all_settings = self.settings_manager.get_all_settings(mask_secrets=False)
            retention_days = int(all_settings.get('LOG_RETENTION_DAYS', {}).get('value') or '7')
            self.logger.info(f"🗑️  Cleaning up logs older than {retention_days} days...")
            cleanup_old_logs(retention_days)
        except Exception as e:
            self.logger.error(f"Log cleanup failed: {e}")

        # STEP 1: Process any pending videos from database (retries, manual adds, etc.)
        # This must come BEFORE the channels check so manually added videos are processed
        pending_videos = self.db.get_pending_videos()
        if pending_videos:
            self.logger.info(f"🔄 Processing {len(pending_videos)} pending videos from database")
            for video in pending_videos:
                channel_id = video.get('channel_id', 'unknown')
                channel_name = video.get('channel_name', 'Unknown')
                # process_video() will log the video title
                self.process_video(video, channel_id, channel_name)

        # STEP 2: Process each channel for new videos (skip if no channels)
        if not self.channels:
            self.logger.warning("No channels configured for automatic checking")
            self.logger.warning("Add channels using the web UI for automatic video discovery")
            # Don't return here - we may have processed pending videos above
        else:
            # Get settings
            skip_shorts = self.config_settings.get('SKIP_SHORTS', 'true').lower() == 'true'

            # Process each channel
            for channel_id in self.channels:
                channel_name = self.channel_names.get(channel_id, channel_id)
                channel_added_at = self.channel_added_dates.get(channel_id)
                self.logger.info(f"📡 Checking: {channel_name}")

                videos = self.youtube_client.get_channel_videos(
                    channel_id=channel_id,
                    max_videos=20,  # Check last 20 videos for new uploads
                    skip_shorts=skip_shorts
                )

                if not videos:
                    self.logger.info(f"   📭 No new videos")
                    continue

                # Process each video
                for video in videos:
                    # Check database status first - skip if already processed
                    if self.db.is_processed(video['id']):
                        existing = self.db.get_video_by_id(video['id'])
                        if existing and existing.get('processing_status') not in [STATUS_PENDING, None]:
                            self.logger.debug(f"   Skipping {existing.get('processing_status')}: {video['title'][:40]}")
                            continue

                    # Get upload date - fetch from yt-dlp first if not available
                    video_upload_date = video.get('published') or video.get('upload_date')

                    # If upload date is missing from initial fetch, get metadata to obtain it
                    if not video_upload_date:
                        self.logger.debug(f"   Fetching metadata to determine upload date for: {video['title'][:40]}")
                        metadata = self.youtube_client.get_video_metadata(video['id'])
                        if metadata:
                            video_upload_date = metadata.get('upload_date', '')
                            # Update video dict with the date for later use
                            video['published'] = video_upload_date

                    # Check if video was uploaded before channel was added (skip old videos)
                    if not self._should_process_video(video_upload_date, channel_added_at):
                        self.logger.info(f"   ⏭️  Skipping old video (uploaded before channel added): {video['title'][:50]}")
                        continue

                    # Process the video
                    self.process_video(video, channel_id, channel_name)

        # Print summary
        self.logger.info("")
        self.logger.info("="*60)
        self.logger.info("Processing Complete")
        self.logger.info(f"   ✅ Processed: {self.stats['videos_processed']} videos")
        self.logger.info(f"   📧 Sent: {self.stats['email_sent']} emails")

        if self.stats['videos_skipped'] > 0:
            self.logger.info(f"   ⏭️  Skipped: {self.stats['videos_skipped']} videos (no transcript)")

        if self.stats['videos_failed'] > 0:
            self.logger.warning(f"   ❌ Failed: {self.stats['videos_failed']} videos")

        if self.stats['api_errors'] > 0:
            self.logger.warning(f"   ⚠️  API Errors: {self.stats['api_errors']}")

        # Log API usage
        self.logger.info(f"   📊 API Calls: {self.stats['api_calls']}")
        estimated_cost = self.stats['api_calls'] * 0.0014  # Rough estimate
        self.logger.info(f"   💰 Estimated Cost: ${estimated_cost:.4f}")

        self.logger.info("="*60)
        self.logger.info("")

        # Release lock after processing
        self._release_lock()


def main():
    """Entry point with error handling"""
    processor = None
    try:
        processor = VideoProcessor()
        processor.run()
    except KeyboardInterrupt:
        print("\n\n👋 Stopped by user")
        if processor:
            processor._release_lock()
        sys.exit(0)
    except Exception as e:
        logger = logging.getLogger('summarizer')
        logger.critical(f"Fatal error: {e}", exc_info=True)
        if processor:
            processor._release_lock()
        sys.exit(1)


if __name__ == "__main__":
    main()
