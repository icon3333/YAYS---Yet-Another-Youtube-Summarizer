#!/usr/bin/env python3
"""
Application-wide constants
Centralizes magic strings and default values to avoid duplication
"""

# ============================================================================
# PROCESSING STATUS VALUES
# ============================================================================
# Used in database and video processing pipeline

STATUS_PENDING = 'pending'
STATUS_PROCESSING = 'processing'
STATUS_FETCHING_METADATA = 'fetching_metadata'
STATUS_FETCHING_TRANSCRIPT = 'fetching_transcript'
STATUS_GENERATING_SUMMARY = 'generating_summary'
STATUS_SENDING_EMAIL = 'sending_email'
STATUS_SUCCESS = 'success'
STATUS_FAILED_TRANSCRIPT = 'failed_transcript'
STATUS_FAILED_AI = 'failed_ai'
STATUS_FAILED_EMAIL = 'failed_email'


# ============================================================================
# FILE PATHS
# ============================================================================

ENV_FILE = '.env'
ENV_EXAMPLE_FILE = '.env.example'
DATABASE_FILE = 'data/videos.db'
PROCESSED_FILE = 'data/processed.txt'
DATA_DIR = 'data'
LOGS_DIR = 'logs'


# ============================================================================
# API AND MODEL DEFAULTS
# ============================================================================

# OpenAI configuration
DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'
DEFAULT_TEMPERATURE = 0.3
MAX_TRANSCRIPT_CHARS = 15000  # ~3750 tokens

# Summary configuration
DEFAULT_SUMMARY_LENGTH = 500
DEFAULT_CHECK_INTERVAL_HOURS = 4

# Retry configuration
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 2  # seconds for general retries
AI_RETRY_BASE_DELAY = 5  # seconds for AI API retries

# Rate limiting
RATE_LIMIT_DELAY = 3  # seconds between API calls


# ============================================================================
# EMAIL CONFIGURATION
# ============================================================================

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_TIMEOUT = 10  # seconds


# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Logging
DEFAULT_LOG_LEVEL = 'INFO'
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_FILE_BACKUP_COUNT = 5

# Database
DEFAULT_MAX_PROCESSED_ENTRIES = 10000

# Web server
WEB_PORT = 8000
WEB_HOST = '0.0.0.0'

# Import/Export
MAX_IMPORT_FILE_SIZE_MB = 50
MAX_IMPORT_FILE_SIZE_BYTES = MAX_IMPORT_FILE_SIZE_MB * 1024 * 1024
