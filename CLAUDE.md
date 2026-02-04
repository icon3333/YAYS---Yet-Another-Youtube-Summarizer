# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YAYS (Yet Another YouTube Summarizer) is a self-hosted Python application that monitors YouTube channels, extracts transcripts, generates AI summaries via OpenAI, and delivers them via email to RSS readers or inboxes.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Docker
**Deployment:** Two containers (web + summarizer) sharing a SQLite database

## Common Commands

### Docker (Production)
```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f
docker compose logs web
docker compose logs summarizer

# Manual video processing
docker exec youtube-summarizer python process_videos.py

# Restart services
docker compose restart

# Rebuild after code changes
docker compose down
docker compose build
docker compose up -d

# Stop services
docker compose down
```

### Local Development
```bash
# Setup
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run web server
python main.py

# Run video processor (one-time)
python process_videos.py

# Access web UI
# http://localhost:8000 (local) or http://localhost:8015 (Docker)
```

### Database
```bash
# Access SQLite database directly
sqlite3 data/videos.db

# Useful queries
sqlite3 data/videos.db "SELECT * FROM videos WHERE processing_status='failed_transcript' LIMIT 5;"
sqlite3 data/videos.db "SELECT key, value FROM settings WHERE type='secret';"
```

## Architecture

### Multi-Container Design
- **Web container** (`youtube-web`): FastAPI server, serves UI at port 8015, manages settings
- **Summarizer container** (`youtube-summarizer`): Runs `start_summarizer.py` (Python, via ENTRYPOINT) in infinite loop, dynamically reads check interval from database
- **Shared state**: Both containers mount `./data/videos.db` for persistence
- **Dynamic configuration**: Check interval is read from database before each processing run (configurable 1-24 hours via Web UI)

### Key Design Patterns

#### 1. Database-Centric Configuration
All configuration is stored in SQLite (`data/videos.db`), not files:
- **Deprecated:** `config.txt` (legacy, no longer used by application code)
- **Current approach:** `settings` table with plain text storage
- **Storage:** All settings (including API keys and passwords) stored unencrypted in database
- **Security:** Designed for single-user homeserver setups (protect database file access)
- **Migration:** `_migrate_decrypt_settings()` in database.py automatically converts legacy encrypted settings to plain text

#### 2. Manager Pattern
Business logic is separated into managers (located in `src/managers/`):
- `ConfigManager`: Channel and prompt management (delegates to VideoDatabase)
- `SettingsManager`: Settings management (API keys, SMTP credentials stored as plain text)
- `ExportManager` / `ImportManager`: Data backup/restore
- `VideoDatabase`: Single source of truth for all persistence

All managers delegate to `VideoDatabase` for SQLite operations.

#### 3. Transcript Extraction Cascade
Four methods tried sequentially until one succeeds (`src/core/transcript.py`):
1. **youtube-transcript-api** (fast, rate-limited)
2. **yt-dlp subtitles** (slower, more reliable)
3. **Direct timedtext API** (scraping fallback)
4. **Supadata.ai API** (optional paid service, most reliable)

Failed attempts are cached in `transcript_cache` table to avoid redundant retries.

#### 4. Process Isolation & Concurrency Safety
- **File locking:** `src/utils/file_lock.py` prevents concurrent processing runs
- **PID tracking:** `.processing.lock` file stores PID of active processor
- **Stuck detection:** Heartbeat monitoring detects abandoned processes
- **Single-writer model:** Only summarizer container writes videos; web container reads

### Video Processing Pipeline

```
Channel Discovery → Video Metadata → Transcript Extract → AI Summary → Email Delivery
     (yt-dlp/RSS)     (yt-dlp)       (4-method cascade)    (OpenAI)      (SMTP)
```

Status progression:
```
pending → processing → fetching_metadata → fetching_transcript → generating_summary → success/failed_*
```

Key implementation: `process_videos.py` (main loop) calls functions from `src/core/`:
- `youtube.py`: Channel/video discovery
- `transcript.py`: Transcript extraction with cascading fallback
- `ai_summarizer.py`: OpenAI GPT integration
- `email_sender.py`: SMTP delivery

## Database Schema

### videos table
- `processing_status`: pending, processing, success, failed_transcript, failed_summary, failed_email
- `source_type`: via_channel (auto-discovered) or via_manual (user-added)
- `transcript_source`: youtube-transcript-api, yt-dlp, timedtext, supadata
- `retry_count`: Max 3 attempts before permanent failure

### settings table
- `type`: secret (plain text), email, enum, integer, text
- `encrypted`: Boolean flag (always 0, legacy field)
- Key settings include:
  - **Secrets:** OPENAI_API_KEY, SMTP_PASS, SUPADATA_API_KEY
  - **Email:** TARGET_EMAIL, SMTP_USER
  - **Configuration:** CHECK_INTERVAL_HOURS, SEND_EMAIL_SUMMARIES, OPENAI_MODEL, LOG_LEVEL, LOG_RETENTION_DAYS
  - **yt-dlp settings:** YTDLP_RATE_LIMIT, YTDLP_SLEEP_INTERVAL, YTDLP_RETRIES (and others)
- **Security:** All values stored as plain text for simplicity in single-user homeserver setups

### channels table
- `enabled`: Boolean to pause channel monitoring
- `added_at`: Videos uploaded before this timestamp are skipped

## Important Files

### Entry Points
- `main.py`: Starts FastAPI web server (uvicorn)
- `process_videos.py`: Main video processing loop
- `start_summarizer.py`: Python wrapper that runs process_videos.py every N hours (replaces former bash script)

### Core Logic
- `src/web/app.py`: FastAPI application (1994 lines, all endpoints)
- `src/managers/database.py`: SQLite operations, schema initialization
- `src/managers/settings_manager.py`: Settings persistence (plain text storage)
- `src/core/transcript.py`: Transcript extraction with 4-method fallback
- `src/core/email_sender.py`: SMTP email delivery with UTF-8 encoding support

### Utilities
- `src/utils/log_cleanup.py`: Automatic deletion of old log files based on retention policy
- `src/utils/log_redactor.py`: Redacts sensitive data (API keys, passwords) from log output before serving
- `src/utils/tail_reader.py`: Efficient tail-based file reading for paginated log viewing

### Configuration
- `docker-compose.yml`: Service definitions, volume mounts (CRITICAL: `./data` bind mount preserves database)
  - **Note:** Still mounts `config.txt` for backward compatibility but application no longer uses it
- `requirements.txt`: Python dependencies (encryption libraries removed)
- `Dockerfile`: Multi-stage build (base → summarizer/web)

## Critical Implementation Details

### 1. Settings Storage
All settings stored as plain text in SQLite database:
- **No encryption:** API keys and passwords stored unencrypted for simplicity (encryption dependencies removed)
- **Single-user design:** Optimized for homeserver setups where database file access is already restricted
- **Migration:** `_migrate_decrypt_settings()` automatically converts legacy encrypted settings on first run
- **Legacy field:** `encrypted` column remains in schema (always 0) for backward compatibility
- **Removed files:** `src/utils/encryption.py` deleted, `cryptography` dependency removed from requirements.txt

### 2. Concurrency Safety
Multiple safeguards prevent concurrent processing:
- File-level lock: `data/.processing.lock` (via `filelock` library)
- PID tracking: Lock file contains PID of active process
- Stuck detection: If lock exists but PID is dead, cleanup and retry

### 3. Video Deduplication
Videos are deduplicated by ID:
- YouTube video ID (11 characters) is primary key
- Channels are checked against `channels.added_at` to skip old videos
- Prevents reprocessing when channels are re-added

### 4. Restart Behavior
Settings changes may require container restart:
- `restart_manager.py` detects container restart via PID change
- Web UI shows restart prompt when needed
- Use `docker compose restart` (NOT `docker compose up -d` which doesn't reload code)

### 5. Web UI Architecture
Single-page application (no React/Vue):
- Server: Jinja2 renders `src/templates/index.html` once
- Client: Vanilla JS in `src/static/js/app.js` handles all interactions
- Polling: Frontend polls REST API every 2 seconds for status updates

## Development Workflow

### Making Code Changes
1. Edit source files in `src/`
2. For web changes: `docker compose restart web`
3. For processor changes: `docker compose restart summarizer`
4. For dependency changes: Rebuild containers (`docker compose down && docker compose build && docker compose up -d`)

### Testing Changes Locally
```bash
# Test web server
python main.py
# Visit http://localhost:8000

# Test video processor
python process_videos.py
# Check logs/summarizer.log
```

### Database Migrations
No formal migration system. To modify schema:
1. Edit `src/managers/database.py` → `initialize_db()`
2. Add ALTER TABLE statements for existing databases
3. Test with fresh database: `rm data/videos.db && python main.py`

### Adding New Settings
1. Add to `DEFAULT_SETTINGS` in `src/managers/settings_manager.py`
2. Specify type: `secret`, `email`, `enum`, `integer`, `text`
3. All settings stored as plain text (no encryption)
4. Add validation in `src/utils/validators.py` if needed

### Adding New API Endpoints
1. Edit `src/web/app.py`
2. Add route with FastAPI decorator: `@app.get("/api/...")` or `@app.post("/api/...")`
3. Use Pydantic models for request/response validation
4. Access database via `VideoDatabase()` instance
5. Update frontend JS in `src/static/js/app.js` to call new endpoint

## Important Conventions

### Error Handling
- Processing errors set `processing_status` to `failed_*` (e.g., `failed_transcript`)
- Error messages stored in `error_message` column
- Max 3 retries via `retry_count` column
- Permanent failures after retry exhaustion

### Logging
- Web logs: stdout (captured by Docker)
- Processor logs: `logs/summarizer.log` (10MB rotation)
- Log levels: DEBUG, INFO, WARNING, ERROR
- Set via `LOG_LEVEL` environment variable

### API Rate Limiting
- 3-second delay between YouTube API calls to avoid rate limits
- Transcript failures cached for 24 hours to reduce load
- OpenAI retries with exponential backoff

### Security Notes
- No authentication on web UI (designed for Tailscale/local access)
- **Secrets stored as plain text** in database for simplicity (encryption removed in favor of filesystem-level protection)
- Protect database file access at filesystem/network level
- SQL injection prevented via parameterized queries
- `.env` file contains legacy configuration (optional), excluded from Git
- **Migration:** Legacy encrypted settings automatically converted to plain text on first run

## Troubleshooting Tips

### "Settings not persisting"
- Check that `./data` directory is mounted in docker-compose.yml
- Verify database file permissions allow container write access
- Check docker logs for database errors

### "Videos stuck in 'processing' status"
- Check for stale `.processing.lock` file
- Restart summarizer container: `docker compose restart summarizer`
- Check logs: `docker compose logs summarizer`

### "Transcript failures"
- Check cascade order: youtube-transcript-api → yt-dlp → timedtext → supadata
- Enable Supadata fallback for better reliability
- View `transcript_cache` table for cached failures

### "Email not sending"
- Verify SMTP credentials in Settings tab
- Check Gmail app password (must be exactly 16 characters, not regular password)
- Ensure UTF-8 characters in video titles are properly encoded (fixed in recent update)
- For international characters, ensure email client supports UTF-8

## Testing

No formal test suite. Manual testing via:
- `test_validation.py`: Validates input sanitization
- Database modules have `if __name__ == '__main__':` blocks for testing

## Recent Improvements

### Logs Viewer & Log Management (commit: b8c7a9e)
- Added in-browser log viewer with tail-based pagination for large log files
- 3 new API endpoints: `GET /api/logs/list`, `GET /api/logs/{log_name}`, `GET /api/logs/{log_name}/download`
- Sensitive data (API keys, passwords, emails) automatically redacted before serving logs
- Automatic old log cleanup based on `LOG_RETENTION_DAYS` setting (default: 30 days)
- New utilities: `log_cleanup.py`, `log_redactor.py`, `tail_reader.py`

### Email Encoding Fix (commit: df928e3)
- Added UTF-8 encoding support for email subject lines using `email.header.Header`
- Properly encodes video titles with international characters
- Fixed encoding issues with emojis and special characters in subject lines

### Gmail App Password Validation (commit: 8e2c1ef)
- Enhanced validation for Gmail SMTP passwords
- Enforces exactly 16 characters (Gmail app password format)
- Improved error messaging for incorrect password format

### Check Interval Backend Setting (commits: c5f7bfb, 77cf3d6)
- Fixed check interval to properly read from database settings
- Removed hardcoded environment variable from docker-compose.yml
- `start_summarizer.py` now dynamically reads `CHECK_INTERVAL_HOURS` from database before each run
- Changes via Web UI take effect on next processing cycle (no restart required)

### Deprecated File Cleanup (commit: 053ed57)
- Removed `src/utils/encryption.py` (encryption no longer used)
- Removed `fix_channel_timestamps.py` (migration script no longer needed)
- Removed `youtube-summarizer.service` (Docker-based deployment only)

**Important:** While `config.txt` is still mounted in docker-compose.yml for backward compatibility, it is no longer used by the application. All configuration is now stored in the database `settings` table.

## Deployment Notes

- Install script: `curl -fsSL https://raw.githubusercontent.com/icon3333/YAYS/main/install.sh | bash`
- Update script: `./update.sh` (pulls code, rebuilds, restarts)
- Data persistence: `./data/videos.db` is bind-mounted (never use named volume)
- Port: Default 8015, configurable in docker-compose.yml
- Access: Designed for Tailscale or local-only access (no authentication)
