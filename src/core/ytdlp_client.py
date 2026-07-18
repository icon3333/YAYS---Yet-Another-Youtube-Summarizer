#!/usr/bin/env python3
"""
YouTube Data Extraction via yt-dlp
Robust channel and video metadata extraction
"""

import re
import logging
import random
from typing import Optional, Dict, List, Any
from time import sleep
from datetime import datetime

import yt_dlp

from src.managers.settings_manager import SettingsManager


logger = logging.getLogger(__name__)


class YTDLPClient:
    """Client for YouTube data extraction via yt-dlp"""

    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY_BASE = 10  # seconds
    DEFAULT_RETRY_DELAY_CAP = 120  # seconds
    DEFAULT_FRAGMENT_RETRIES = 3
    DEFAULT_SLEEP_INTERVAL = 0
    DEFAULT_MAX_SLEEP_INTERVAL = 0
    DEFAULT_SLEEP_REQUESTS = 0
    DEFAULT_CONCURRENT_FRAGMENTS = 1

    DEFAULT_OPTIONS = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'ignoreerrors': False,
        'no_check_certificate': True,
        'noprogress': True,
    }

    def __init__(self, db_path: str = "data/videos.db"):
        """Initialize yt-dlp client"""
        self.db_path = db_path
        self.settings = self._load_settings()
        self.ydl_opts = self.DEFAULT_OPTIONS.copy()

        # Load pacing configuration
        self.rate_limit = self._parse_rate_limit(self._get_setting_value('YTDLP_RATE_LIMIT'))
        self.sleep_interval = self._get_int_setting('YTDLP_SLEEP_INTERVAL', self.DEFAULT_SLEEP_INTERVAL)
        self.max_sleep_interval = self._get_int_setting('YTDLP_MAX_SLEEP_INTERVAL', self.DEFAULT_MAX_SLEEP_INTERVAL)
        self.sleep_requests = self._get_int_setting('YTDLP_SLEEP_REQUESTS', self.DEFAULT_SLEEP_REQUESTS)
        self.concurrent_fragments = self._get_int_setting('YTDLP_CONCURRENT_FRAGMENTS', self.DEFAULT_CONCURRENT_FRAGMENTS)

        # Retry configuration
        self.max_retries = self._get_int_setting('YTDLP_RETRIES', self.DEFAULT_MAX_RETRIES)
        self.fragment_retry_attempts = self._get_int_setting('YTDLP_FRAGMENT_RETRIES', self.DEFAULT_FRAGMENT_RETRIES)
        self.retry_delay_base = self._get_int_setting('YTDLP_RETRY_BASE_DELAY', self.DEFAULT_RETRY_DELAY_BASE)
        self.retry_delay_cap = self._get_int_setting('YTDLP_RETRY_MAX_DELAY', self.DEFAULT_RETRY_DELAY_CAP)

        # Normalise configuration values
        self.max_retries = max(self.max_retries, 1)
        self.fragment_retry_attempts = max(self.fragment_retry_attempts, 1)
        self.retry_delay_base = max(self.retry_delay_base, 1)
        self.retry_delay_cap = max(self.retry_delay_cap, self.retry_delay_base)
        self.sleep_interval = max(self.sleep_interval, 0)
        self.max_sleep_interval = max(self.max_sleep_interval, self.sleep_interval)
        self.sleep_requests = max(self.sleep_requests, 0)
        self.concurrent_fragments = max(self.concurrent_fragments, 1)

        self._apply_runtime_options()
        logger.debug(
            "YTDLPClient initialized (rate_limit=%s, sleep=%ss-%ss, request_sleep<=%ss, retries=%s, fragments=%s)",
            self.rate_limit,
            self.sleep_interval,
            self.max_sleep_interval,
            self.sleep_requests,
            self.max_retries,
            self.fragment_retry_attempts,
        )

    # =========
    # Settings
    # =========

    def _load_settings(self) -> Dict[str, Dict[str, Any]]:
        """Load yt-dlp-related settings from the database."""
        try:
            manager = SettingsManager(db_path=self.db_path)
            return manager.get_all_settings(mask_secrets=False)
        except Exception as exc:
            logger.warning(f"Failed to load yt-dlp settings from database: {exc}")
            return {}

    def _get_setting_value(self, key: str) -> Optional[str]:
        """Retrieve a raw setting value from loaded settings."""
        entry = self.settings.get(key)
        if not entry:
            return None

        value = entry.get('value')
        if value in (None, ''):
            return entry.get('default')
        return str(value)

    def _get_int_setting(self, key: str, default: int) -> int:
        """Parse an integer setting with fallback."""
        raw_value = self._get_setting_value(key)
        if raw_value in (None, ''):
            return default
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            logger.warning(f"Invalid integer for {key}: {raw_value!r}, using default {default}")
            return default

    def _parse_rate_limit(self, value: Optional[str]) -> Optional[int]:
        """
        Parse human-friendly rate limit formats (e.g., 800K, 1M) to bytes per second.
        Returns None when no rate limit should be applied.
        """
        if not value:
            return None

        cleaned = value.strip().lower()
        if not cleaned:
            return None

        multiplier = 1
        if cleaned.endswith('k'):
            multiplier = 1024
            cleaned = cleaned[:-1]
        elif cleaned.endswith('m'):
            multiplier = 1024 * 1024
            cleaned = cleaned[:-1]

        try:
            numeric = float(cleaned)
            if numeric <= 0:
                return None
            return int(numeric * multiplier)
        except ValueError:
            logger.warning(f"Invalid rate limit format: {value!r}, ignoring")
            return None

    def _apply_runtime_options(self) -> None:
        """Apply loaded configuration to yt-dlp option bag."""
        if self.rate_limit:
            self.ydl_opts['ratelimit'] = self.rate_limit

        self.ydl_opts['retries'] = self.max_retries
        self.ydl_opts['fragment_retries'] = self.fragment_retry_attempts
        self.ydl_opts['extractor_retries'] = self.max_retries

        if self.sleep_interval > 0:
            self.ydl_opts['sleep_interval'] = self.sleep_interval
            if self.max_sleep_interval and self.max_sleep_interval >= self.sleep_interval:
                self.ydl_opts['max_sleep_interval'] = self.max_sleep_interval

        if self.sleep_requests > 0:
            # The python API mirrors --sleep-requests as sleep_interval_requests
            self.ydl_opts['sleep_interval_requests'] = self.sleep_requests

        if self.concurrent_fragments:
            self.ydl_opts['concurrent_fragment_downloads'] = self.concurrent_fragments

    # =============
    # Rate limiting
    # =============

    def _sleep_before_request(self, context: str) -> None:
        """Inject jittered pause before a network-bound yt-dlp call."""
        if self.sleep_requests <= 0:
            return

        delay = random.uniform(0, float(self.sleep_requests))
        if delay <= 0:
            return

        logger.debug(f"Sleeping {delay:.2f}s before yt-dlp request ({context})")
        sleep(delay)

    def _sleep_after_operation(self, context: str) -> None:
        """Pause after successful yt-dlp operation to mimic human pacing."""
        if self.sleep_interval <= 0:
            return

        upper = max(self.max_sleep_interval, self.sleep_interval)
        if upper <= self.sleep_interval:
            delay = float(self.sleep_interval)
        else:
            delay = random.uniform(float(self.sleep_interval), float(upper))

        if delay <= 0:
            return

        logger.debug(f"Sleeping {delay:.2f}s after yt-dlp operation ({context})")
        sleep(delay)

    def _compute_backoff_delay(self, attempt: int) -> float:
        """Compute exponential backoff delay with jitter."""
        delay = self.retry_delay_base * (2 ** attempt)
        delay = min(delay, self.retry_delay_cap)
        jitter = random.uniform(0, float(self.retry_delay_base))
        return max(float(self.retry_delay_base), float(delay) + jitter)

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Detect whether an error is likely caused by rate limiting."""
        error_str = str(error).lower()
        return '429' in error_str or 'rate' in error_str or 'quota' in error_str

    def extract_channel_info(self, channel_input: str) -> Optional[Dict]:
        """
        Extract channel ID and name from any URL format

        Supports:
        - UC channel IDs: UCddiUEpeqJcYeBxX1IVBKvQ
        - @handles: @mkbhd
        - Channel URLs: youtube.com/channel/UC...
        - Custom URLs: youtube.com/c/LinusTechTips
        - User URLs: youtube.com/user/marquesbrownlee

        Returns:
        {
            'channel_id': 'UC...',
            'channel_name': 'Display Name',
            'channel_url': 'https://...'
        }
        """
        url = self._normalize_channel_url(channel_input)
        logger.debug(f"Extracting channel info from: {url}")

        for attempt in range(self.max_retries):
            try:
                self._sleep_before_request('channel info')

                opts = self.ydl_opts.copy()
                opts['extract_flat'] = 'in_playlist'
                opts['playlistend'] = 1

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                    if not info:
                        self._sleep_after_operation('channel info')
                        logger.warning(f"No info returned for: {channel_input}")
                        return None

                    channel_id = info.get('channel_id') or info.get('uploader_id')
                    channel_name = info.get('channel') or info.get('uploader')
                    channel_url = info.get('channel_url')

                    if channel_id:
                        self._sleep_after_operation('channel info')
                        logger.info(f"✓ Channel found: {channel_name} ({channel_id})")
                        return {
                            'channel_id': channel_id,
                            'channel_name': channel_name,
                            'channel_url': channel_url,
                        }
                    else:
                        logger.warning(f"No channel_id in response for: {channel_input}")
                        self._sleep_after_operation('channel info')
                        return None

            except yt_dlp.utils.DownloadError as e:
                error_str = str(e)
                if self._is_rate_limit_error(e):
                    if attempt < self.max_retries - 1:
                        delay = self._compute_backoff_delay(attempt)
                        logger.warning(
                            f"Rate limited, retrying in {delay:.1f}s (attempt {attempt+1}/{self.max_retries})"
                        )
                        sleep(delay)
                        continue
                logger.error(f"yt-dlp download error: {e}")
                return None

            except Exception as e:
                logger.error(f"yt-dlp error extracting channel: {e}")
                return None

        logger.error(f"Max retries reached for: {channel_input}")
        return None

    def get_channel_videos(self, channel_id: str, max_videos: int = 5, skip_shorts: bool = True) -> List[Dict]:
        """
        Fetch recent videos from channel

        Returns: List of video metadata dicts
        """
        # Build channel URL
        if channel_id.startswith('@'):
            channel_url = f"https://www.youtube.com/{channel_id}/videos"
        else:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"

        logger.debug(f"Fetching videos from: {channel_url}")

        for attempt in range(self.max_retries):
            try:
                self._sleep_before_request('channel videos')

                opts = self.ydl_opts.copy()
                opts['playlistend'] = max_videos * 3  # Account for shorts
                opts['extract_flat'] = 'in_playlist'

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)

                    if not info or 'entries' not in info:
                        self._sleep_after_operation('channel videos')
                        logger.debug(f"No entries for channel: {channel_id}")
                        return []

                    videos = []
                    for entry in info['entries']:
                        if not entry:
                            continue

                        # Skip shorts if configured
                        video_url = entry.get('url', '')
                        if skip_shorts and '/shorts/' in video_url:
                            logger.debug(f"Skipping short: {entry.get('title', 'Unknown')[:40]}")
                            continue

                        videos.append({
                            'id': entry['id'],
                            'title': entry.get('title', 'Unknown'),
                            'url': video_url,
                            'published': entry.get('upload_date', ''),
                        })

                        if len(videos) >= max_videos:
                            break

                    logger.debug(f"Found {len(videos)} videos")
                    self._sleep_after_operation('channel videos')
                    return videos

            except Exception as e:
                if attempt < self.max_retries - 1:
                    if self._is_rate_limit_error(e):
                        delay = self._compute_backoff_delay(attempt)
                    else:
                        delay = min(self.retry_delay_base * (attempt + 1), self.retry_delay_cap)
                    logger.warning(
                        f"Error fetching videos, retrying in {delay:.1f}s (attempt {attempt+1}/{self.max_retries})"
                    )
                    sleep(delay)
                    continue
                logger.error(f"Failed to fetch videos: {e}")
                return []

        return []

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Extract detailed video metadata

        Returns metadata dict with duration, views, upload_date, etc.
        """
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.debug(f"Fetching metadata for: {video_id}")

        for attempt in range(self.max_retries):
            try:
                self._sleep_before_request('video metadata')

                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)

                    if not info:
                        self._sleep_after_operation('video metadata')
                        logger.warning(f"No metadata for: {video_id}")
                        return None

                    # Extract and format metadata
                    duration_sec = info.get('duration', 0)
                    duration_str = self._format_duration(duration_sec)

                    views = info.get('view_count', 0)
                    views_str = self._format_views(views)

                    upload_date = info.get('upload_date', '')
                    upload_date_str = self._format_upload_date(upload_date)

                    metadata = {
                        'id': info.get('id'),
                        'title': info.get('title'),
                        'url': info.get('webpage_url'),
                        'duration': duration_sec,
                        'duration_string': duration_str,
                        'view_count': views,
                        'view_count_string': views_str,
                        'upload_date': upload_date,
                        'upload_date_string': upload_date_str,
                        'description': info.get('description', ''),
                        'channel': info.get('channel') or info.get('uploader'),
                        'uploader': info.get('uploader'),
                        'channel_id': info.get('channel_id'),
                    }

                    logger.debug(f"✓ Metadata: {duration_str}, {views_str}")
                    self._sleep_after_operation('video metadata')
                    return metadata

            except Exception as e:
                if attempt < self.max_retries - 1:
                    delay = self._compute_backoff_delay(attempt) if self._is_rate_limit_error(e) else min(
                        self.retry_delay_base * (attempt + 1), self.retry_delay_cap
                    )
                    logger.warning(
                        f"Error fetching metadata, retrying in {delay:.1f}s (attempt {attempt+1}/{self.max_retries})"
                    )
                    sleep(delay)
                    continue
                logger.error(f"Failed to get metadata for {video_id}: {e}")
                return None

        return None

    # Transcript extraction removed: handled by youtube-transcript-api.

    def _normalize_channel_url(self, channel_input: str) -> str:
        """Convert any channel input to a valid YouTube URL"""
        # Fix malformed URLs (https:/ -> https://)
        if channel_input.startswith('https:/') and not channel_input.startswith('https://'):
            channel_input = channel_input.replace('https:/', 'https://', 1)
        elif channel_input.startswith('http:/') and not channel_input.startswith('http://'):
            channel_input = channel_input.replace('http:/', 'http://', 1)

        # Already a URL
        if channel_input.startswith('http'):
            # Ensure /videos suffix for better results
            if '/videos' not in channel_input:
                channel_input = channel_input.rstrip('/') + '/videos'
            return channel_input

        # @handle
        if channel_input.startswith('@'):
            return f"https://www.youtube.com/{channel_input}/videos"

        # UC channel ID
        if re.match(r'^UC[\w-]{22}$', channel_input):
            return f"https://www.youtube.com/channel/{channel_input}/videos"

        # Fallback: treat as handle
        return f"https://www.youtube.com/@{channel_input}/videos"

    def _format_duration(self, seconds: int) -> str:
        """Format seconds to human-readable duration"""
        if not seconds:
            return "Unknown"

        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}m {secs}s"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            secs = seconds % 60
            if secs > 0:
                return f"{hours}h {mins}m {secs}s"
            else:
                return f"{hours}h {mins}m"

    def _format_views(self, views: int) -> str:
        """Format view count to human-readable string"""
        if not views:
            return "Unknown views"

        if views < 1000:
            return f"{views:,} views"
        elif views < 1_000_000:
            return f"{views/1000:.1f}K views"
        else:
            return f"{views/1_000_000:.1f}M views"

    def _format_upload_date(self, upload_date: str) -> str:
        """Format YYYYMMDD to YYYY-MM-DD"""
        if not upload_date or len(upload_date) != 8:
            return "Unknown"

        try:
            # Parse and format
            dt = datetime.strptime(upload_date, '%Y%m%d')
            return dt.strftime('%Y-%m-%d')
        except:
            return upload_date
