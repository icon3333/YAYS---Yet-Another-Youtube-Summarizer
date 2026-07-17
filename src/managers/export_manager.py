"""
Export Manager - Handles data export operations for YAYS.

Supports two export levels:
1. Feed Export - Channels + videos with summaries
2. Complete Backup - Feed + settings + AI prompt (no credentials)

Supports two formats:
- JSON (structured, import-capable)
- CSV (analysis-friendly, videos only)
"""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.managers.database import VideoDatabase
from src.managers.config_manager import ConfigManager
from src.managers.settings_manager import SettingsManager


logger = logging.getLogger(__name__)


class ExportManager:
    """Manages export operations for channels, videos, and settings."""

    # Schema version for export files (semver format)
    SCHEMA_VERSION = "1.0"

    # Application metadata
    APP_NAME = "YAYS"
    APP_VERSION = "2.2.0"

    # Export levels
    EXPORT_LEVEL_FEED = "feed"
    EXPORT_LEVEL_COMPLETE = "complete"

    # Credentials to exclude from export (security - these should NOT be exported)
    # Only actual secrets are excluded - API keys and passwords
    # Email addresses (TARGET_EMAIL, SMTP_USER) ARE exported for backup purposes
    EXCLUDED_CREDENTIALS = {
        "OPENAI_API_KEY",   # OpenAI API key - never export
        "SMTP_PASS",        # Gmail App Password - never export
        "SMTP_PASSWORD",    # Alias for SMTP_PASS - never export
    }

    def __init__(
        self,
        db_path: str = "data/videos.db",
        env_path: str = ".env",  # Unused, kept for backward compatibility
    ):
        """
        Initialize ExportManager.

        Args:
            db_path: Path to SQLite database
            env_path: Unused, kept for backward compatibility
        """
        self.db = VideoDatabase(db_path)
        self.config_manager = ConfigManager(db_path=db_path)
        self.settings_manager = SettingsManager(db_path=db_path)

    def export_feed_json(self) -> Dict[str, Any]:
        """
        Export Feed level data to JSON structure.

        Returns:
            Dictionary with export_level, channels, videos, metadata

        Raises:
            Exception: If database or config read fails
        """
        logger.info("Generating Feed Export (JSON)")

        try:
            channels = self._get_channels()
            videos = self._get_videos()

            export_data = {
                "export_level": self.EXPORT_LEVEL_FEED,
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "schema_version": self.SCHEMA_VERSION,
                "metadata": {
                    "application": self.APP_NAME,
                    "application_version": self.APP_VERSION,
                    "total_channels": len(channels),
                    "total_videos": len(videos),
                },
                "channels": channels,
                "videos": videos,
            }

            logger.info(
                f"Feed Export generated: {len(channels)} channels, {len(videos)} videos"
            )
            return export_data

        except Exception as e:
            logger.error(f"Feed Export failed: {e}")
            raise

    def export_complete_backup_json(self) -> Dict[str, Any]:
        """
        Export Complete Backup level data to JSON structure.

        Includes: Feed data + settings + AI prompt (no credentials)

        Returns:
            Dictionary with all exportable data

        Raises:
            Exception: If database, config, or settings read fails
        """
        logger.info("Generating Complete Backup Export (JSON)")

        try:
            # Start with Feed Export data
            export_data = self.export_feed_json()

            # Override export level
            export_data["export_level"] = self.EXPORT_LEVEL_COMPLETE

            # Add settings (non-secret only)
            settings = self._get_settings()
            export_data["settings"] = settings

            logger.info(
                f"Complete Backup generated: {len(export_data['channels'])} channels, "
                f"{len(export_data['videos'])} videos, {len(settings)} settings"
            )
            return export_data

        except Exception as e:
            logger.error(f"Complete Backup Export failed: {e}")
            raise

    def export_videos_csv(self) -> str:
        """
        Export videos to CSV format.

        Returns:
            CSV string with headers and all video rows

        Raises:
            Exception: If database read fails
        """
        logger.info("Generating Videos Export (CSV)")

        try:
            videos = self._get_videos()

            # Create CSV in memory
            output = io.StringIO()

            # Write UTF-8 BOM for Excel compatibility
            output.write("\ufeff")

            # Define CSV columns (19 total)
            fieldnames = [
                "video_id",
                "title",
                "channel_id",
                "channel_name",
                "duration_seconds",
                "duration_formatted",
                "view_count",
                "upload_date",
                "processing_status",
                "summary_text",
                "summary_length",
                "email_sent",
                "processed_date",
                "error_message",
                "hours_saved",
                "youtube_url",
                "channel_url",
                "created_at",
                "updated_at",
            ]

            writer = csv.DictWriter(
                output,
                fieldnames=fieldnames,
                quoting=csv.QUOTE_NONNUMERIC,
                lineterminator="\r\n",
            )

            writer.writeheader()

            # Write video rows
            for video in videos:
                row = self._format_csv_row(video)
                writer.writerow(row)

            csv_content = output.getvalue()
            output.close()

            logger.info(f"CSV Export generated: {len(videos)} videos")
            return csv_content

        except Exception as e:
            logger.error(f"CSV Export failed: {e}")
            raise

    def _get_channels(self) -> List[Dict[str, Any]]:
        """
        Extract channels from ConfigManager.

        Returns:
            List of channel dictionaries with channel_id, channel_name, added_date
        """
        try:
            # Use ConfigManager's built-in export method (single source of truth)
            channels_list = self.config_manager.export_channels()

            if not channels_list:
                logger.warning("No channels found in config")
                return []

            logger.debug(f"Extracted {len(channels_list)} channels from config")
            return channels_list

        except Exception as e:
            logger.error(f"Failed to extract channels: {e}")
            raise

    def _get_videos(self) -> List[Dict[str, Any]]:
        """
        Extract all videos from VideoDatabase.

        Returns:
            List of video dictionaries with all fields
        """
        try:
            videos = self.db.export_all_videos()
            logger.debug(f"Extracted {len(videos)} videos from database")
            return videos

        except Exception as e:
            logger.error(f"Failed to extract videos: {e}")
            raise

    def _get_settings(self) -> Dict[str, Any]:
        """
        Extract non-secret settings from database.

        Excludes credentials for security.

        Returns:
            Dictionary of settings
        """
        settings = {}

        try:
            # Get all settings from database
            all_settings = self.config_manager.get_settings()

            # Get AI prompt template
            ai_prompt = self.config_manager.get_prompt()
            if ai_prompt:
                settings["ai_prompt_template"] = ai_prompt

            # Get application settings (exclude credentials)
            env_settings = self.settings_manager.get_all_settings(mask_secrets=False)

            # Settings that should be exported as boolean (env settings)
            env_boolean_settings = {"SEND_EMAIL_SUMMARIES"}
            # Settings that should be exported as integers (env settings)
            env_integer_settings = {"CHECK_INTERVAL_HOURS", "MAX_PROCESSED_ENTRIES"}

            env_exported_count = 0
            for key, value in env_settings.items():
                if key not in self.EXCLUDED_CREDENTIALS:
                    # Extract actual value from nested dict structure
                    # get_all_settings() returns {'key': {'value': 'actual_value', 'type': '...', ...}}
                    if isinstance(value, dict) and 'value' in value:
                        extracted_value = value['value']
                    else:
                        extracted_value = value  # Fallback for simple values

                    # Convert boolean settings to actual boolean
                    if key in env_boolean_settings and isinstance(extracted_value, str):
                        extracted_value = extracted_value.lower() in ("true", "1")
                    # Convert integer settings to actual integers
                    elif key in env_integer_settings and isinstance(extracted_value, str) and extracted_value.isdigit():
                        extracted_value = int(extracted_value)

                    settings[key] = extracted_value
                    env_exported_count += 1
                else:
                    logger.debug(f"Skipping credential: {key}")

            # Add config settings (non-env settings)
            config_keys = [
                "SUMMARY_LENGTH",
                "USE_SUMMARY_LENGTH",
                "SKIP_SHORTS",
                "CHECK_INTERVAL_MINUTES",
                "MAX_FEED_ENTRIES",
            ]

            # Settings that should be exported as boolean
            boolean_settings = {"USE_SUMMARY_LENGTH", "SKIP_SHORTS"}

            for key in config_keys:
                value = all_settings.get(key)
                if value is not None:
                    # Convert boolean settings first (before int conversion)
                    if key in boolean_settings:
                        if isinstance(value, str):
                            # Accept "true", "false", "1", "0"
                            value = value.lower() in ("true", "1")
                        # If already boolean, keep it
                    # Convert string booleans to actual booleans (for non-boolean settings)
                    elif isinstance(value, str) and value.lower() in ("true", "false"):
                        value = value.lower() == "true"
                    # Convert string integers to actual integers
                    elif isinstance(value, str) and value.isdigit():
                        value = int(value)
                    settings[key] = value

            logger.debug(f"Extracted {len(settings)} total settings from database")
            return settings

        except Exception as e:
            logger.error(f"Failed to extract settings: {e}")
            raise

    def _format_csv_row(self, video: Dict[str, Any]) -> Dict[str, str]:
        """
        Format video dictionary as CSV row with calculated fields.

        Args:
            video: Video dictionary from database

        Returns:
            Dictionary with all CSV fields
        """
        # Calculate duration formatted (MM:SS or HH:MM:SS)
        duration_seconds = video.get("duration_seconds", 0)
        if duration_seconds >= 3600:
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60
            duration_formatted = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_formatted = f"{minutes}:{seconds:02d}"

        # Calculate hours saved (duration * 0.8 / 3600)
        hours_saved = round(duration_seconds * 0.8 / 3600, 2)

        # Generate URLs
        video_id = video.get("video_id", "")
        channel_id = video.get("channel_id", "")
        youtube_url = f"https://youtube.com/watch?v={video_id}" if video_id else ""
        channel_url = (
            f"https://youtube.com/channel/{channel_id}" if channel_id else ""
        )

        # Convert boolean to string
        email_sent = str(video.get("email_sent", False)).lower()

        return {
            "video_id": video.get("video_id", ""),
            "title": video.get("title", ""),
            "channel_id": channel_id,
            "channel_name": video.get("channel_name", ""),
            "duration_seconds": str(duration_seconds),
            "duration_formatted": duration_formatted,
            "view_count": str(video.get("view_count") or ""),
            "upload_date": video.get("upload_date") or "",
            "processing_status": video.get("processing_status", ""),
            "summary_text": video.get("summary_text") or "",
            "summary_length": str(video.get("summary_length") or ""),
            "email_sent": email_sent,
            "processed_date": video.get("processed_date") or "",
            "error_message": video.get("error_message") or "",
            "hours_saved": str(hours_saved),
            "youtube_url": youtube_url,
            "channel_url": channel_url,
            "created_at": video.get("created_at") or "",
            "updated_at": video.get("updated_at") or "",
        }

    def generate_export_filename(
        self, export_type: str, file_format: str = "json"
    ) -> str:
        """
        Generate timestamped filename for export.

        Args:
            export_type: 'feed_export', 'videos', or 'full_backup'
            file_format: 'json' or 'csv'

        Returns:
            Filename with timestamp (e.g., 'yays_feed_export_2025-10-20_14-30.json')
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return f"yays_{export_type}_{timestamp}.{file_format}"
