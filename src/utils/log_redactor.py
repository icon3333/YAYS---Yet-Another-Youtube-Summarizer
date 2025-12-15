"""
Log Redactor Utility

Redacts sensitive information from log content before displaying or downloading.
Protects API keys, passwords, email addresses, and other secrets.
"""

import re
from typing import List, Tuple

# Pre-compile regex patterns for performance
_COMPILED_PATTERNS: List[Tuple[re.Pattern, str]] = []


def _initialize_patterns():
    """Initialize and compile regex patterns once at module load."""
    global _COMPILED_PATTERNS
    if _COMPILED_PATTERNS:
        return

    patterns = [
        # OpenAI API keys (sk-...)
        (r'sk-[A-Za-z0-9_-]{20,}', 'sk-***REDACTED***'),

        # Supadata API keys (sd_...)
        (r'sd_[A-Za-z0-9_-]{10,}', 'sd_***REDACTED***'),

        # Generic API keys, secrets, tokens, passwords
        # Matches KEY=value, SECRET:value, PASS=value, TOKEN=value
        (r'((?:API_?KEY|SECRET|TOKEN|PASS(?:WORD)?)\s*[=:]\s*)([^\s,\)\]\'\"]+)', r'\1***REDACTED***'),

        # Email addresses (preserve structure for debugging context)
        (r'\b([\w\.\-+]+)@([\w\.\-]+\.\w+)\b', r'***@***'),

        # Gmail app passwords (16 character strings in format: xxxx xxxx xxxx xxxx)
        (r'\b([a-z]{4}\s[a-z]{4}\s[a-z]{4}\s[a-z]{4})\b', r'***REDACTED***'),
    ]

    # Compile all patterns with IGNORECASE flag
    _COMPILED_PATTERNS = [
        (re.compile(pattern, re.IGNORECASE), replacement)
        for pattern, replacement in patterns
    ]


def redact_sensitive_data(log_content: str) -> str:
    """
    Redact sensitive information from log content.

    Args:
        log_content: Raw log text

    Returns:
        Log text with sensitive data replaced with ***REDACTED***
    """
    if not log_content:
        return ''

    # Initialize patterns if not already done
    _initialize_patterns()

    # Apply all pre-compiled patterns
    redacted = log_content
    for compiled_pattern, replacement in _COMPILED_PATTERNS:
        redacted = compiled_pattern.sub(replacement, redacted)

    return redacted


# Initialize patterns on module import
_initialize_patterns()


if __name__ == '__main__':
    # Test the redaction
    test_logs = """
    2025-12-15 14:23:45 [INFO] web: Server started
    2025-12-15 14:23:46 [INFO] web: OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890
    2025-12-15 14:23:47 [INFO] web: Using email user@example.com
    2025-12-15 14:23:48 [DEBUG] web: SMTP_PASS=abcd efgh ijkl mnop
    2025-12-15 14:23:49 [INFO] web: SUPADATA_API_KEY: sd_1234567890abcdefghij
    """

    print("Original logs:")
    print(test_logs)
    print("\nRedacted logs:")
    print(redact_sensitive_data(test_logs))
