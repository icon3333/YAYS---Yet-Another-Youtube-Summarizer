#!/usr/bin/env python3
"""
Settings Manager - Database-backed settings (plain text storage)
Thin wrapper around VideoDatabase for settings operations
"""

import re
from typing import Dict, Optional, Tuple, Any

from src.utils.validators import is_valid_email, is_valid_openai_key


class SettingsManager:
    """
    Database-backed settings manager.

    ALL settings stored in database as plain text:
    - Secrets (API keys, passwords) stored as plain text
    - Non-secrets (emails, config) stored as plain text
    - All operations delegate to VideoDatabase
    - No file operations!
    - Designed for single-user homeserver setups
    """

    def __init__(self, env_path='.env', db_path='data/videos.db', lock_timeout=10):
        """
        Initialize SettingsManager.

        Args:
            env_path: Unused, kept for backward compatibility
            db_path: Path to SQLite database
            lock_timeout: Unused, kept for backward compatibility
        """
        # Import here to avoid circular dependency
        from src.managers.database import VideoDatabase
        self.db = VideoDatabase(db_path)

        # Define settings schema for validation
        self.env_schema = {
            # Secrets (stored as plain text in database)
            'OPENAI_API_KEY': {
                'type': 'secret',
                'required': True,
                'pattern': r'^sk-[A-Za-z0-9_-]{20,}$',
                'description': 'OpenAI API Key (for ChatGPT)'
            },
            'SMTP_PASS': {
                'type': 'secret',
                'required': True,
                'min_length': 16,
                'max_length': 16,
                'description': 'Gmail app password (16 chars)'
            },
            'SUPADATA_API_KEY': {
                'type': 'secret',
                'required': False,
                'pattern': r'^sd_[A-Za-z0-9_-]{10,}$',
                'description': 'Supadata.ai API Key for transcript service',
                'default': ''
            },
            # Non-secrets (plaintext in database)
            'TARGET_EMAIL': {
                'type': 'email',
                'required': True,
                'pattern': r'^[\w\.\-+]+@[\w\.\-]+\.\w+$',
                'description': 'Email address for receiving summaries'
            },
            'SMTP_USER': {
                'type': 'email',
                'required': True,
                'pattern': r'^[\w\.\-+]+@[\w\.\-]+\.\w+$',
                'description': 'Gmail SMTP username'
            },
            # Application settings
            'LOG_LEVEL': {
                'type': 'enum',
                'required': False,
                'default': 'INFO',
                'options': ['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                'description': 'Logging verbosity level'
            },
            'CHECK_INTERVAL_HOURS': {
                'type': 'integer',
                'required': False,
                'default': '4',
                'min': 1,
                'max': 24,
                'description': 'How often to check for new videos (hours)'
            },
            'MAX_PROCESSED_ENTRIES': {
                'type': 'integer',
                'required': False,
                'default': '10000',
                'min': 100,
                'max': 100000,
                'description': 'Max video IDs to track before rotation'
            },
            'SEND_EMAIL_SUMMARIES': {
                'type': 'enum',
                'required': False,
                'default': 'true',
                'options': ['true', 'false'],
                'description': 'Send summaries via email'
            },
            'OPENAI_MODEL': {
                'type': 'text',
                'required': False,
                'default': 'gpt-4o-mini',
                'description': 'OpenAI model to use for summaries'
            },
            'TRANSCRIPT_PROVIDER': {
                'type': 'enum',
                'required': False,
                'default': 'legacy',
                'options': ['legacy', 'supadata'],
                'description': 'Transcript provider (legacy or supadata)'
            },
            # yt-dlp throttling and retry behaviour
            'YTDLP_RATE_LIMIT': {
                'type': 'text',
                'required': False,
                'default': '800K',
                'description': 'Maximum yt-dlp download rate per connection (e.g., 800K, 1M)'
            },
            'YTDLP_SLEEP_INTERVAL': {
                'type': 'integer',
                'required': False,
                'default': '60',
                'min': 0,
                'max': 3600,
                'description': 'Minimum pause (seconds) between yt-dlp operations'
            },
            'YTDLP_MAX_SLEEP_INTERVAL': {
                'type': 'integer',
                'required': False,
                'default': '180',
                'min': 0,
                'max': 7200,
                'description': 'Maximum pause (seconds) between yt-dlp operations'
            },
            'YTDLP_SLEEP_REQUESTS': {
                'type': 'integer',
                'required': False,
                'default': '3',
                'min': 0,
                'max': 120,
                'description': 'Randomised pause ceiling (seconds) before individual yt-dlp HTTP requests'
            },
            'YTDLP_CONCURRENT_FRAGMENTS': {
                'type': 'integer',
                'required': False,
                'default': '1',
                'min': 1,
                'max': 5,
                'description': 'Maximum parallel fragment downloads for yt-dlp'
            },
            'YTDLP_RETRIES': {
                'type': 'integer',
                'required': False,
                'default': '10',
                'min': 1,
                'max': 50,
                'description': 'Total retry attempts for yt-dlp extraction failures'
            },
            'YTDLP_FRAGMENT_RETRIES': {
                'type': 'integer',
                'required': False,
                'default': '15',
                'min': 1,
                'max': 100,
                'description': 'Retry attempts for yt-dlp fragment downloads'
            },
            'YTDLP_RETRY_BASE_DELAY': {
                'type': 'integer',
                'required': False,
                'default': '10',
                'min': 1,
                'max': 600,
                'description': 'Base delay (seconds) for exponential backoff when rate limited'
            },
            'YTDLP_RETRY_MAX_DELAY': {
                'type': 'integer',
                'required': False,
                'default': '120',
                'min': 10,
                'max': 3600,
                'description': 'Maximum delay (seconds) for exponential backoff when rate limited'
            },
            'LOG_RETENTION_DAYS': {
                'type': 'integer',
                'required': False,
                'default': '7',
                'min': 1,
                'max': 30,
                'description': 'Automatically delete logs older than this many days'
            }
        }

    def _mask_secret(self, value: str) -> str:
        """Mask sensitive values for display."""
        if not value or not isinstance(value, str):
            return ''

        # Ensure value is stripped of whitespace
        value = value.strip()

        if value.startswith('sk-'):
            # OpenAI/API key: sk-***...***xxx
            if len(value) > 15:
                return f"{value[:7]}***...***{value[-4:]}"
            return 'sk-***'
        elif value.startswith('sd_'):
            # Supadata API key: sd_***...***xxx
            if len(value) > 15:
                return f"{value[:5]}***...***{value[-4:]}"
            return 'sd_***'
        else:
            # Generic password: all dots
            return '•' * min(len(value), 16)

    def get_setting(self, key: str) -> Optional[str]:
        """
        Get a single setting value from database.

        Args:
            key: Setting key

        Returns:
            Setting value or None if not found
        """
        return self.db.get_setting(key)

    def get_all_settings(self, mask_secrets=True) -> Dict[str, Any]:
        """
        Get all settings from database with optional masking.

        Args:
            mask_secrets: If True, mask secret values for display

        Returns:
            Dict with structure: { key: { value, masked, type, description, ... } }
        """
        settings = {}

        try:
            # Get all settings from database (automatically decrypted)
            db_settings = self.db.get_all_settings()

            # Process each defined setting
            for key, schema in self.env_schema.items():
                # Get value from database or use default
                value = db_settings.get(key, {}).get('value', schema.get('default', ''))

                setting_info = {
                    'value': value,
                    'type': schema['type'],
                    'description': schema.get('description', ''),
                    'required': schema.get('required', False)
                }

                # Add type-specific metadata
                if schema['type'] == 'enum':
                    setting_info['options'] = schema.get('options', [])
                    setting_info['default'] = schema.get('default', '')

                elif schema['type'] == 'integer':
                    setting_info['min'] = schema.get('min')
                    setting_info['max'] = schema.get('max')
                    setting_info['default'] = schema.get('default', '')

                # Mask secrets if requested
                if mask_secrets and schema['type'] == 'secret':
                    setting_info['masked'] = self._mask_secret(value)
                    setting_info['value'] = ''  # Don't send actual value to client
                else:
                    setting_info['masked'] = value

                settings[key] = setting_info

        except Exception as e:
            print(f"⚠️ Error reading settings: {e}")
            # Return schema defaults
            for key, schema in self.env_schema.items():
                settings[key] = {
                    'value': '',
                    'masked': '',
                    'type': schema['type'],
                    'description': schema.get('description', ''),
                    'required': schema.get('required', False)
                }

        return settings

    def validate_setting(self, key: str, value: str) -> Tuple[bool, str]:
        """
        Validate a single setting value.

        Args:
            key: Setting key
            value: Setting value

        Returns:
            Tuple of (is_valid, error_message)
        """
        if key not in self.env_schema:
            return False, f"Unknown setting: {key}"

        schema = self.env_schema[key]

        # Allow empty values (means "don't update this field")
        if not value:
            return True, ''

        # Type-specific validation
        if schema['type'] == 'secret':
            if key == 'OPENAI_API_KEY':
                if not is_valid_openai_key(value):
                    return False, f"Invalid format for {key}"
            elif 'pattern' in schema:
                if not re.match(schema['pattern'], value):
                    return False, f"Invalid format for {key}"

            # Check length constraints
            if 'min_length' in schema:
                clean_value = value.replace(' ', '')
                if len(clean_value) < schema['min_length']:
                    return False, f"{key} must be at least {schema['min_length']} characters"

            if 'max_length' in schema:
                clean_value = value.replace(' ', '')
                if len(clean_value) > schema['max_length']:
                    return False, f"{key} must be at most {schema['max_length']} characters"

        elif schema['type'] == 'email':
            if value and not is_valid_email(value):
                return False, f"Invalid email format for {key}"

        elif schema['type'] == 'enum':
            if value and value not in schema.get('options', []):
                return False, f"{key} must be one of: {', '.join(schema['options'])}"

        elif schema['type'] == 'integer':
            try:
                int_value = int(value)
                if 'min' in schema and int_value < schema['min']:
                    return False, f"{key} must be at least {schema['min']}"
                if 'max' in schema and int_value > schema['max']:
                    return False, f"{key} must be at most {schema['max']}"
            except ValueError:
                return False, f"{key} must be a valid integer"

        return True, ''

    def update_setting(self, key: str, value: str) -> Tuple[bool, str]:
        """
        Update a single setting in database.

        Args:
            key: Setting key
            value: Setting value (stored as plain text)

        Returns:
            Tuple of (success, message)
        """
        # Validate first
        is_valid, error_msg = self.validate_setting(key, value)
        if not is_valid:
            return False, error_msg

        if key not in self.env_schema:
            return False, f"Unknown setting: {key}"

        # Clean value (remove spaces from passwords)
        if key == 'SMTP_PASS':
            value = value.replace(' ', '')

        try:
            # Update in database (stored as plain text)
            self.db.set_setting(key, value)
            return True, f"Updated {key} successfully"

        except Exception as e:
            return False, f"Failed to update {key}: {str(e)}"

    def update_multiple_settings(self, settings: Dict[str, str]) -> Tuple[bool, str, list]:
        """
        Update multiple settings at once.

        Args:
            settings: Dict mapping setting key to value (stored as plain text)

        Returns:
            Tuple of (success, message, list of errors)
        """
        errors = []

        # Validate all first
        for key, value in settings.items():
            is_valid, error_msg = self.validate_setting(key, value)
            if not is_valid:
                errors.append(error_msg)

        if errors:
            return False, "Validation failed", errors

        try:
            # Filter out empty values and clean passwords
            non_empty_settings = {}
            for key, value in settings.items():
                if not value:
                    continue  # Skip empty values

                # Clean value if needed
                if key == 'SMTP_PASS':
                    value = value.replace(' ', '')

                non_empty_settings[key] = value

            if not non_empty_settings:
                return True, "No settings to update", []

            # Update all settings in database (stored as plain text)
            updated_count = self.db.set_multiple_settings(non_empty_settings)

            return True, f"Updated {updated_count} settings successfully", []

        except Exception as e:
            return False, f"Failed to update settings: {str(e)}", []

    def check_restart_required(self) -> bool:
        """
        Check if restart is required for changes to take effect.

        Returns:
            Always True - settings changes require restart
        """
        return True


# Test functions for credentials
def test_openai_key(api_key: str) -> Tuple[bool, str]:
    """
    Test OpenAI API key by making a simple API call.

    Args:
        api_key: OpenAI API key

    Returns:
        Tuple of (success, message)
    """
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        # Make a minimal API call to test the key
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=5,
            messages=[{"role": "user", "content": "Hi"}]
        )

        return True, "✅ OpenAI API key is valid"

    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "authentication" in error_msg.lower() or "api_key" in error_msg.lower():
            return False, "❌ Invalid API key"
        elif "rate" in error_msg.lower() or "quota" in error_msg.lower():
            return False, "⚠️ Rate limited or quota exceeded (but key appears valid)"
        else:
            return False, f"❌ API test failed: {error_msg[:100]}"


def test_smtp_credentials(smtp_user: str, smtp_pass: str) -> Tuple[bool, str]:
    """
    Test SMTP credentials by attempting connection.

    Args:
        smtp_user: SMTP username
        smtp_pass: SMTP password

    Returns:
        Tuple of (success, message)
    """
    try:
        import smtplib

        # Attempt to connect and authenticate
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.quit()

        return True, "✅ SMTP credentials are valid"

    except smtplib.SMTPAuthenticationError:
        return False, "❌ Invalid email or password"

    except smtplib.SMTPException as e:
        return False, f"❌ SMTP error: {str(e)[:100]}"

    except Exception as e:
        return False, f"❌ Connection failed: {str(e)[:100]}"


if __name__ == '__main__':
    # Test the settings manager
    print("Testing SettingsManager...")

    manager = SettingsManager(db_path='test_settings.db')

    # Test getting settings
    print("\n1. Getting all settings (masked):")
    settings = manager.get_all_settings(mask_secrets=True)
    for key, info in list(settings.items())[:3]:
        print(f"   {key}: {info['masked']} ({info['type']})")

    # Test validation
    print("\n2. Testing validation:")
    test_cases = [
        ('LOG_LEVEL', 'INFO', True),
        ('LOG_LEVEL', 'INVALID', False),
        ('CHECK_INTERVAL_HOURS', '4', True),
        ('CHECK_INTERVAL_HOURS', '0', False),
    ]

    for key, value, expected_valid in test_cases:
        is_valid, msg = manager.validate_setting(key, value)
        status = "✅" if is_valid == expected_valid else "❌"
        print(f"   {status} {key}={value}: {msg if not is_valid else 'Valid'}")

    # Cleanup
    import os
    try:
        os.remove('test_settings.db')
    except:
        pass

    print("\n✅ Tests complete")
