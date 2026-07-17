#!/usr/bin/env python3
"""
Configuration Manager - Database-backed configuration
Thin wrapper around VideoDatabase for channels, settings, and prompt
"""

from typing import Dict, List, Tuple, Optional

from src.utils.validators import is_valid_channel_id


class ConfigManager:
    """
    Database-backed configuration manager.

    All operations delegate to VideoDatabase.
    No file operations - everything in SQLite!
    """

    def __init__(self, db_path='data/videos.db'):
        """
        Initialize ConfigManager.

        Args:
            db_path: Path to SQLite database
        """
        # Import here to avoid circular dependency
        from src.managers.database import VideoDatabase
        self.db = VideoDatabase(db_path)

    # ========================
    # Channels
    # ========================

    def get_channels(self) -> Tuple[List[str], Dict[str, str], Dict[str, Optional[str]]]:
        """
        Get enabled channels from database.

        Returns:
            Tuple of (channel_ids list, channel_names dict, channel_added_dates dict)
            - channel_ids: List of enabled channel IDs
            - channel_names: Dict mapping channel_id to display name
            - channel_added_dates: Dict mapping channel_id to added_at timestamp
        """
        return self.db.get_enabled_channels()

    def add_channel(self, channel_id: str, channel_name: str = None) -> bool:
        """
        Add a channel to database.

        Args:
            channel_id: YouTube channel ID
            channel_name: Optional display name

        Returns:
            True if added, False if already exists
        """
        if not is_valid_channel_id(channel_id):
            print(f"❌ Invalid channel ID: {channel_id}")
            return False

        result = self.db.add_channel(channel_id, channel_name or channel_id)
        if not result:
            print(f"⚠️ Channel already exists: {channel_id}")
        return result

    def remove_channel(self, channel_id: str) -> bool:
        """
        Remove a channel from database.

        Args:
            channel_id: YouTube channel ID

        Returns:
            True if removed, False if not found
        """
        result = self.db.remove_channel(channel_id)
        if not result:
            print(f"⚠️ Channel not found: {channel_id}")
        return result

    def set_channels(self, channels: List[str], channel_names: Optional[Dict[str, str]] = None) -> bool:
        """
        Set channels list (replaces existing channels).

        Args:
            channels: List of channel IDs
            channel_names: Optional dict mapping channel_id to name

        Returns:
            True if successful
        """
        return self.db.set_channels(channels, channel_names or {})

    # ========================
    # AI Prompt Template
    # ========================

    def get_prompt(self) -> str:
        """Get the current AI prompt template from database."""
        return self.db.get_setting('ai_prompt_template') or self._get_default_prompt()

    def set_prompt(self, prompt: str) -> bool:
        """
        Update the AI prompt template in database.

        Args:
            prompt: New prompt template

        Returns:
            True if successful
        """
        try:
            self.db.set_setting('ai_prompt_template', prompt)
            return True
        except Exception as e:
            print(f"❌ Error updating prompt: {e}")
            return False

    def reset_prompt_to_default(self) -> bool:
        """Reset the AI prompt template to default."""
        return self.set_prompt(self._get_default_prompt())

    def _get_default_prompt(self) -> str:
        """Get default AI prompt template."""
        return """You are summarizing a YouTube video. Create a concise summary that:
1. Captures the main points in 2-3 paragraphs
2. Highlights what's valuable or interesting
3. Mentions any actionable takeaways
4. Indicates who would benefit from watching

Keep the tone conversational and focus on value.

Title: {title}
Duration: {duration}
Transcript: {transcript}"""

    # ========================
    # Settings
    # ========================

    def get_settings(self) -> Dict[str, str]:
        """
        Get all settings from database.

        Returns:
            Dict mapping setting key to value
        """
        db_settings = self.db.get_all_settings()
        # Convert to simple key-value dict for backward compatibility
        return {key: info['value'] for key, info in db_settings.items()}

    def set_setting(self, key: str, value: str) -> bool:
        """
        Update a single setting in database.

        Args:
            key: Setting key
            value: New value

        Returns:
            True if successful
        """
        try:
            self.db.set_setting(key, value)
            return True
        except Exception as e:
            print(f"❌ Error updating setting {key}: {e}")
            return False

    def import_settings(self, settings: Dict[str, str]) -> int:
        """
        Import multiple settings at once.

        Args:
            settings: Dict mapping setting key to value

        Returns:
            Number of settings imported
        """
        try:
            return self.db.set_multiple_settings(settings)
        except Exception as e:
            print(f"❌ Error importing settings: {e}")
            return 0

    def import_channels(self, channels: List[Dict[str, str]], merge: bool = True) -> int:
        """
        Import channels from list.

        Args:
            channels: List of channel dicts with channel_id and optional channel_name
            merge: If True, add to existing; if False, replace all

        Returns:
            Number of channels imported
        """
        if not merge:
            # Replace all channels
            self.db.set_channels([], {})

        imported = 0
        for channel in channels:
            channel_id = channel.get('channel_id')
            channel_name = channel.get('channel_name', channel_id)

            if channel_id and self.add_channel(channel_id, channel_name):
                imported += 1

        return imported

    def export_channels(self) -> List[Dict[str, str]]:
        """
        Export channels for backup/export purposes.

        Returns:
            List of channel dicts with channel_id, channel_name
        """
        channels = self.db.get_all_channels()
        return [
            {
                'channel_id': ch['channel_id'],
                'channel_name': ch['channel_name']
            }
            for ch in channels
        ]

    def reset_all_settings(self) -> bool:
        """
        Reset all config settings to defaults.

        Returns:
            True if successful
        """
        default_settings = {
            'SUMMARY_LENGTH': '500',
            'USE_SUMMARY_LENGTH': 'false',
            'SKIP_SHORTS': 'true',
        }

        try:
            for key, value in default_settings.items():
                self.db.set_setting(key, value)
            return True
        except Exception as e:
            print(f"❌ Error resetting settings: {e}")
            return False

    def ensure_config_exists(self) -> bool:
        """
        Ensure configuration exists in database.
        For backward compatibility - always returns True now.

        Returns:
            True
        """
        return True


if __name__ == '__main__':
    # Test the config manager
    print("Testing ConfigManager...")

    mgr = ConfigManager(db_path='test_config.db')

    # Test channels
    print("\n1. Testing channels:")
    mgr.add_channel('UCtest123', 'Test Channel')
    channels, names = mgr.get_channels()
    print(f"   Channels: {channels}")
    print(f"   Names: {names}")

    # Test settings
    print("\n2. Testing settings:")
    mgr.set_setting('TEST_SETTING', 'test_value')
    settings = mgr.get_settings()
    print(f"   TEST_SETTING: {settings.get('TEST_SETTING')}")

    # Test prompt
    print("\n3. Testing prompt:")
    mgr.set_prompt("Test prompt template")
    prompt = mgr.get_prompt()
    print(f"   Prompt: {prompt[:50]}...")

    # Cleanup
    import os
    try:
        os.remove('test_config.db')
    except:
        pass

    print("\n✅ Tests complete")
