#!/usr/bin/env python3
"""
YouTube Channel and Video Operations
Handles discovery via yt-dlp with RSS fallback (transcripts handled separately)
"""

import re
import logging
from typing import Optional, List, Dict

import feedparser

try:
    from src.core.ytdlp_client import YTDLPClient
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False


logger = logging.getLogger(__name__)


class YouTubeClient:
    """Client for YouTube channel and video operations"""

    def __init__(
        self,
        use_ytdlp: bool = True,
        ytdlp_client: Optional["YTDLPClient"] = None,
    ):
        """Initialize client with yt-dlp or RSS fallback"""
        self.use_ytdlp = use_ytdlp and YTDLP_AVAILABLE

        if self.use_ytdlp:
            self.ytdlp = ytdlp_client if ytdlp_client is not None else YTDLPClient()
            logger.info("YouTubeClient initialized with yt-dlp discovery support")
        else:
            if use_ytdlp and not YTDLP_AVAILABLE:
                logger.warning("yt-dlp requested but not available, falling back to RSS")
            else:
                logger.info("YouTubeClient initialized with RSS")
            self.ytdlp = None

    def extract_channel_id(self, channel_input: str) -> Optional[str]:
        """
        Extract channel ID from various formats
        Returns channel ID or None if invalid
        """
        # Already a valid channel ID
        if re.match(r'^UC[\w-]{22}$', channel_input):
            return channel_input

        # Handle @username format
        if channel_input.startswith('@'):
            return channel_input

        # Extract from URL patterns
        patterns = [
            r'youtube\.com/channel/(UC[\w-]{22})',
            r'youtube\.com/@([\w-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, channel_input)
            if match:
                return match.group(1)

        # Assume it's a raw channel ID
        return channel_input

    def get_channel_videos(self, channel_id: str, max_videos: int = 5, skip_shorts: bool = True) -> List[Dict]:
        """
        Fetch recent videos from YouTube channel
        Uses yt-dlp if available, falls back to RSS
        Returns list of video dicts
        """
        # Use yt-dlp if available
        if self.use_ytdlp:
            return self.ytdlp.get_channel_videos(channel_id, max_videos, skip_shorts)

        # Fallback to RSS
        return self._get_channel_videos_rss(channel_id, max_videos, skip_shorts)

    def _get_channel_videos_rss(self, channel_id: str, max_videos: int = 5, skip_shorts: bool = True) -> List[Dict]:
        """
        Fetch recent videos via RSS feed (fallback method)
        """
        clean_id = self.extract_channel_id(channel_id)
        if not clean_id:
            logger.warning(f"Could not extract channel ID from: {channel_id}")
            return []

        # Build RSS feed URL
        if clean_id.startswith('@'):
            # Handle format might not work with RSS - log warning
            logger.warning(f"@handle format may not work with RSS: {clean_id}")
            logger.warning("Please use channel ID format (UC...) instead")
            return []

        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={clean_id}"

        try:
            feed = feedparser.parse(feed_url)

            # Check for errors
            if feed.bozo:
                logger.warning(f"Invalid RSS feed for {channel_id}: {feed.bozo_exception}")
                return []

            if not feed.entries:
                logger.debug(f"No videos found for {channel_id}")
                return []

            videos = []
            for entry in feed.entries[:max_videos * 2]:  # Check extra to account for shorts
                # Skip YouTube Shorts if configured
                if skip_shorts and '/shorts/' in entry.link:
                    logger.debug(f"Skipping short: {entry.title}")
                    continue

                videos.append({
                    'id': entry.yt_videoid,
                    'title': entry.title,
                    'url': entry.link,
                    'published': entry.published
                })

                if len(videos) >= max_videos:
                    break

            return videos

        except Exception as e:
            logger.error(f"Error fetching RSS for {channel_id}: {e}")
            return []

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Get detailed video metadata (duration, views, upload date)
        Only available with yt-dlp
        """
        if self.use_ytdlp:
            return self.ytdlp.get_video_metadata(video_id)
        else:
            logger.debug("Video metadata not available without yt-dlp")
            return None

    def extract_channel_info(self, channel_input: str) -> Optional[Dict]:
        """
        Extract channel ID and name from any URL format
        Only available with yt-dlp
        """
        if self.use_ytdlp:
            return self.ytdlp.extract_channel_info(channel_input)
        else:
            # Fallback: just extract ID
            channel_id = self.extract_channel_id(channel_input)
            if channel_id:
                return {
                    'channel_id': channel_id,
                    'channel_name': None,
                    'channel_url': None
                }
            return None
