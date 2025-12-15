#!/usr/bin/env python3
"""
YouTube Summarizer - Web Interface (Modern Minimalist)
Black, white, grey only - Two column layout
With auto-fetch channel names from YouTube
"""

import os
import sys
import logging
import subprocess
import signal
import json
import io
from pathlib import Path
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel, field_validator
from typing import Dict, List, Optional
import re
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables from .env file
# Create .env from .env.example if it doesn't exist
if not os.path.exists('.env') and os.path.exists('.env.example'):
    import shutil
    shutil.copy2('.env.example', '.env')
    print("✅ Created .env from .env.example")

load_dotenv()

# Setup logging with dynamic log level from environment
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)

log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

# Create root logger
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, log_level, logging.INFO))

# Console handler (stdout for Docker logs)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_format)
root_logger.addHandler(console_handler)

# File handler (shared logs directory)
file_handler = RotatingFileHandler(
    os.path.join(log_dir, 'web.log'),
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(console_format)
root_logger.addHandler(file_handler)

logger = logging.getLogger('web')
logger.info(f"Web app starting with log level: {log_level}")

# Import shared modules
from src.managers.config_manager import ConfigManager
from src.managers.settings_manager import SettingsManager, test_openai_key, test_smtp_credentials
from src.managers.database import VideoDatabase
from src.managers.restart_manager import detect_runtime_environment, restart_application
from src.managers.export_manager import ExportManager
from src.managers.import_manager import ImportManager
from src.core.ytdlp_client import YTDLPClient
from src.core.youtube import YouTubeClient

app = FastAPI(
    title="YAYS - Yet Another Youtube Summarizer",
    version="0.1",
    description="Modern minimalist design"
)

# Enable CORS to allow the UI to call the API from other origins during dev
# Safe to allow all origins here since we don't use cookies/auth headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files with custom StaticFiles class to disable caching
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from starlette.responses import Response

class NoCacheStaticFiles(StarletteStaticFiles):
    """StaticFiles with cache-control headers to prevent caching"""
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app.mount("/static", NoCacheStaticFiles(directory="src/static", html=False), name="static")

# Setup templates (disable auto_reload caching in production)
templates = Jinja2Templates(directory="src/templates")
templates.env.auto_reload = True
templates.env.cache = None

# Initialize managers (all use database now!)
config_manager = ConfigManager(db_path='data/videos.db')
settings_manager = SettingsManager(db_path='data/videos.db')
video_db = VideoDatabase('data/videos.db')
export_manager = ExportManager(db_path='data/videos.db')
import_manager = ImportManager(db_path='data/videos.db')
ytdlp_client = YTDLPClient()
youtube_client = YouTubeClient(use_ytdlp=True)

# Initialize background scheduler
scheduler = BackgroundScheduler()


def scheduled_video_check():
    """Run process_videos.py as background task (triggered by scheduler)"""
    logger.info("Scheduled video check started")
    try:
        # Use sys.executable to ensure we use the same Python interpreter (venv)
        subprocess.Popen([sys.executable, 'process_videos.py'])
        logger.info("Background processing started successfully")
    except Exception as e:
        logger.error(f"Failed to start scheduled processing: {e}")


@app.on_event("startup")
def start_scheduler():
    """Start the background scheduler when the app starts"""
    try:
        # Read interval from database settings, fall back to schema default
        env_settings = settings_manager.get_all_settings(mask_secrets=False)
        check_interval_setting = env_settings.get('CHECK_INTERVAL_HOURS', {})

        # Use value from database, or fall back to schema default (no hardcoded values)
        interval_hours = int(check_interval_setting.get('value') or
                           check_interval_setting.get('default', '4'))

        scheduler.add_job(
            scheduled_video_check,
            'interval',
            hours=interval_hours,
            id='video_check',
            replace_existing=True
        )
        scheduler.start()

        logger.info(f"✅ Background scheduler started (every {interval_hours}h)")

    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


@app.on_event("shutdown")
def shutdown_scheduler():
    """Shutdown the scheduler gracefully when the app stops"""
    try:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")


# Pydantic models with validation (V2)
class ChannelUpdate(BaseModel):
    channels: List[str]
    names: Dict[str, str]

    @field_validator('channels')
    @classmethod
    def validate_channels(cls, channels):
        """Validate channel ID format"""
        for channel_id in channels:
            if not re.match(r'^(UC[\w-]{22}|@[\w-]+|[\w-]{10,})$', channel_id):
                raise ValueError(f'Invalid channel ID format: {channel_id}')
        return channels

    @field_validator('names')
    @classmethod
    def validate_names(cls, names):
        """Validate channel names"""
        for channel_id, name in names.items():
            if len(name) > 100:
                raise ValueError(f'Channel name too long: {name}')
            if '<' in name or '>' in name or '"' in name:
                raise ValueError(f'Invalid characters in channel name: {name}')
        return names


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the main web interface"""
    return templates.TemplateResponse("index.html", {"request": request})



@app.get("/api/channels")
async def get_channels():
    """API endpoint to retrieve current channels"""
    try:
        channels, names, _ = config_manager.get_channels()
        logger.info(f"Loaded {len(channels)} channels")
        return {"channels": channels, "names": names}
    except Exception as e:
        logger.error(f"Error loading channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/channels")
async def save_channels(data: ChannelUpdate):
    """API endpoint to save updated channel list"""
    try:
        success = config_manager.set_channels(data.channels, data.names)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save config")
        logger.info(f"Saved {len(data.channels)} channels")
        return {"status": "success", "message": f"Saved {len(data.channels)} channels"}
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# DEPRECATED: This endpoint is no longer used - channels are added via /api/channels
# and videos are processed by the background worker (/api/videos/process-now)
# Kept for backward compatibility but returns immediate success
@app.post("/api/channels/{channel_id}/fetch-initial-videos")
async def fetch_initial_videos(channel_id: str):
    """
    [DEPRECATED] This endpoint is no longer used.
    Channels are added via /api/channels POST, and videos are processed by background worker.
    """
    logger.warning(f"Deprecated endpoint called: /api/channels/{channel_id}/fetch-initial-videos")
    return {
        "status": "success",
        "message": "Channel processing will happen in background",
        "videos_fetched": 0
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        config_manager.ensure_config_exists()
        return {"status": "healthy", "version": "0.1"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/api/ytdlp/timing")
async def get_ytdlp_timing():
    """
    Get yt-dlp timing configuration for frontend countdown timers
    Returns estimated wait times for various operations
    """
    try:
        return {
            "sleep_requests": ytdlp_client.sleep_requests,
            "sleep_interval": ytdlp_client.sleep_interval,
            "max_sleep_interval": ytdlp_client.max_sleep_interval,
            "retry_delay_base": ytdlp_client.retry_delay_base,
            "max_retries": ytdlp_client.max_retries,
            # Estimated times for different operations (in seconds)
            "estimated_channel_fetch": ytdlp_client.sleep_requests + ytdlp_client.sleep_interval + 2,
            "estimated_video_fetch": ytdlp_client.sleep_requests + ytdlp_client.sleep_interval + 3,
            "estimated_metadata_fetch": ytdlp_client.sleep_requests + ytdlp_client.sleep_interval + 1
        }
    except Exception as e:
        logger.error(f"Error getting yt-dlp timing: {e}")
        # Return safe defaults
        return {
            "sleep_requests": 0,
            "sleep_interval": 0,
            "max_sleep_interval": 0,
            "retry_delay_base": 10,
            "max_retries": 3,
            "estimated_channel_fetch": 5,
            "estimated_video_fetch": 8,
            "estimated_metadata_fetch": 3
        }


@app.get("/api/fetch-channel-name/{channel_input:path}")
async def fetch_channel_name(channel_input: str):
    """
    Fetch channel name and ID from YouTube using yt-dlp
    Accepts: channel ID (UCxxxx), @handle, or YouTube URLs
    """
    try:
        # Decode and fix common URL encoding issues
        from urllib.parse import unquote
        channel_input = unquote(channel_input)

        # Fix malformed URLs (https:/ -> https://)
        if channel_input.startswith('https:/') and not channel_input.startswith('https://'):
            channel_input = channel_input.replace('https:/', 'https://', 1)
        elif channel_input.startswith('http:/') and not channel_input.startswith('http://'):
            channel_input = channel_input.replace('http:/', 'http://', 1)

        logger.debug(f"Fetch channel name for: {channel_input}")

        # Use yt-dlp for robust channel ID extraction
        channel_info = ytdlp_client.extract_channel_info(channel_input)

        if not channel_info:
            raise HTTPException(status_code=404, detail="Channel not found or could not be resolved")

        channel_id = channel_info['channel_id']
        channel_name = channel_info['channel_name']

        logger.info(f"Fetched channel name: {channel_name} for {channel_id}")

        return {
            "channel_id": channel_id,
            "channel_name": channel_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching channel name for '{channel_input}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch channel name: {str(e)}")


# ============================================================================
# SETTINGS API ENDPOINTS
# ============================================================================

class SettingUpdate(BaseModel):
    """Model for updating a single setting"""
    key: str
    value: str


class MultipleSettingsUpdate(BaseModel):
    """Model for updating multiple settings at once"""
    settings: Dict[str, str]


class PromptUpdate(BaseModel):
    """Model for updating the prompt template"""
    prompt: str

    @field_validator('prompt')
    @classmethod
    def validate_prompt(cls, prompt):
        """Validate prompt has required placeholders"""
        if len(prompt.strip()) < 10:
            raise ValueError('Prompt is too short')
        if len(prompt) > 5000:
            raise ValueError('Prompt is too long (max 5000 chars)')
        return prompt


class CredentialTest(BaseModel):
    """Model for testing credentials"""
    credential_type: str  # 'openai' or 'smtp'
    test_value: Optional[str] = None  # For OpenAI API key
    test_user: Optional[str] = None   # For SMTP user
    test_pass: Optional[str] = None   # For SMTP password


class SingleVideoAdd(BaseModel):
    """Model for adding a single video manually"""
    video_url: str

    @field_validator('video_url')
    @classmethod
    def validate_video_url(cls, url):
        """Validate YouTube video URL format"""
        if not url or len(url.strip()) < 5:
            raise ValueError('Video URL is required')
        # Basic validation - detailed parsing happens in the endpoint
        url_lower = url.lower()
        if 'youtube.com' not in url_lower and 'youtu.be' not in url_lower and len(url) != 11:
            raise ValueError('Invalid YouTube URL format')
        return url.strip()


@app.get("/api/settings")
async def get_settings():
    """Get all settings (with masked credentials)"""
    try:
        # Get .env settings (masked)
        env_settings = settings_manager.get_all_settings(mask_secrets=True)

        # Get config settings from database
        config_settings = config_manager.get_settings()

        logger.info("Retrieved all settings")

        return {
            "env": env_settings,
            "config": config_settings,
            "restart_required": False
        }

    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings")
async def update_settings(data: MultipleSettingsUpdate):
    """Update multiple settings at once"""
    try:
        # Debug logging
        logger.info(f"Received settings update request with {len(data.settings)} settings")
        logger.debug(f"Settings keys: {list(data.settings.keys())}")

        env_updates = {}
        config_updates = {}

        # Separate env vs config settings
        for key, value in data.settings.items():
            if key in settings_manager.env_schema:
                env_updates[key] = value
            elif key in ['SUMMARY_LENGTH', 'USE_SUMMARY_LENGTH', 'SKIP_SHORTS']:
                config_updates[key] = value

        results = {"env": None, "config": None, "restart_required": False}

        # Update env settings (stored in database)
        if env_updates:
            logger.info(f"Updating {len(env_updates)} env settings: {list(env_updates.keys())}")
            success, message, errors = settings_manager.update_multiple_settings(env_updates)
            if not success:
                logger.error(f"Validation failed: {errors}")
                raise HTTPException(status_code=400, detail={"message": message, "errors": errors})

            results["env"] = message
            results["restart_required"] = True
            logger.info(f"Updated env settings in database: {list(env_updates.keys())}")

        # Update config settings (stored in database)
        if config_updates:
            # Validate config settings before writing
            validation_errors = []

            for key, value in config_updates.items():
                if key == 'SUMMARY_LENGTH':
                    if value and not value.isdigit():
                        validation_errors.append(f"SUMMARY_LENGTH must be a number")
                    elif value and (int(value) < 100 or int(value) > 10000):
                        validation_errors.append(f"SUMMARY_LENGTH must be between 100 and 10000")

                elif key in ['USE_SUMMARY_LENGTH', 'SKIP_SHORTS']:
                    if value and value not in ['true', 'false']:
                        validation_errors.append(f"{key} must be 'true' or 'false'")

            if validation_errors:
                logger.error(f"Config validation failed: {validation_errors}")
                raise HTTPException(status_code=400, detail={"message": "Validation failed", "errors": validation_errors})

            # Update settings in database
            try:
                updated_count = 0
                for key, value in config_updates.items():
                    # Skip empty values (partial update support)
                    if not value:
                        continue

                    success = config_manager.set_setting(key, value)
                    if success:
                        updated_count += 1
                    else:
                        logger.warning(f"Failed to update config setting: {key}")

                results["config"] = f"Updated {updated_count} config settings"
                logger.info(f"Updated config settings in database: {list(config_updates.keys())}")

            except Exception as e:
                logger.error(f"Error updating config settings: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings/prompt")
async def get_prompt():
    """Get the current prompt template"""
    try:
        prompt = config_manager.get_prompt()

        logger.info("Retrieved prompt template")

        return {
            "prompt": prompt,
            "length": len(prompt)
        }

    except Exception as e:
        logger.error(f"Error getting prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings/prompt")
async def update_prompt(data: PromptUpdate):
    """Update the prompt template"""
    try:
        # Validate prompt
        if not data.prompt or len(data.prompt.strip()) < 10:
            raise HTTPException(status_code=400, detail="Prompt must be at least 10 characters")

        # Use config_manager for thread-safe update with locking and backup
        success = config_manager.set_prompt(data.prompt)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update prompt")

        logger.info("Updated prompt template")

        return {
            "status": "success",
            "message": "Prompt updated successfully",
            "restart_required": False
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings/restart")
async def restart_app():
    """Restart the application (Docker containers or Python processes)"""
    try:
        # Detect environment and get restart instructions
        env_type, command = detect_runtime_environment()

        # Attempt restart
        result = restart_application()

        logger.info(f"Restart requested - Type: {result['restart_type']}, Success: {result['success']}")

        # For Python mode, schedule the restart after response is sent
        if result['restart_type'] == 'python' and result['success']:
            import asyncio
            import sys

            async def delayed_restart():
                await asyncio.sleep(1)  # Give time for response to be sent

                # Check restart method
                restart_method = result.get('restart_method', 'execv')

                if restart_method == 'docker_exit':
                    # Exit to trigger Docker's restart policy
                    logger.info("Exiting to trigger Docker restart...")
                    sys.exit(0)
                else:
                    # Native Python restart using execv
                    if 'restart_command' in result:
                        logger.info("Executing Python restart...")
                        os.execv(result['restart_command'][0], result['restart_command'])

            asyncio.create_task(delayed_restart())

        return result

    except Exception as e:
        logger.error(f"Error during restart: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings/environment")
async def get_environment():
    """Get the detected runtime environment info"""
    try:
        env_type, command = detect_runtime_environment()

        return {
            "environment": env_type,
            "restart_command": command,
            "in_docker": env_type == 'docker'
        }

    except Exception as e:
        logger.error(f"Error detecting environment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/openai/models")
async def get_openai_models():
    """Fetch available OpenAI models from API"""
    try:
        import openai

        # Get API key from database (via settings manager)
        all_settings = settings_manager.get_all_settings(mask_secrets=False)
        api_key = all_settings.get('OPENAI_API_KEY', {}).get('value', '')

        if not api_key:
            # Return a default list if no API key is configured
            return {
                "models": [
                    {"id": "gpt-4o", "name": "GPT-4o (Latest, Most Capable)"},
                    {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Fast & Affordable)"},
                    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
                    {"id": "gpt-4", "name": "GPT-4"},
                    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
                ],
                "source": "default"
            }

        # Fetch models from OpenAI API
        client = openai.OpenAI(api_key=api_key)
        models_response = client.models.list()

        # Filter for text/chat models only (exclude image, audio, embedding, moderation, etc.)
        chat_models = []
        model_priorities = {
            "gpt-4o": 1,
            "gpt-4o-mini": 2,
            "gpt-4-turbo": 3,
            "gpt-4": 4,
            "gpt-3.5-turbo": 5,
            "o1": 6,
            "o3": 7
        }

        for model in models_response.data:
            model_id = model.id
            model_id_lower = model_id.lower()

            # Include only text/chat models
            is_text_model = (
                # GPT chat models (exclude instruct variants)
                (model_id_lower.startswith("gpt-") and not model_id_lower.endswith("-instruct")) or
                # o1 and o3 reasoning models
                model_id_lower.startswith("o1") or
                model_id_lower.startswith("o3")
            )

            # Exclude non-text models
            is_excluded = (
                "dall-e" in model_id_lower or
                "whisper" in model_id_lower or
                "tts" in model_id_lower or
                "embedding" in model_id_lower or
                "moderation" in model_id_lower or
                "vision" in model_id_lower or
                "audio" in model_id_lower
            )

            if is_text_model and not is_excluded:
                # Use base model name for priority
                base_name = model_id.split("-")[0] + "-" + model_id.split("-")[1] if "-" in model_id else model_id
                if "turbo" in model_id:
                    base_name += "-turbo"
                elif "mini" in model_id:
                    base_name += "-mini"

                priority = model_priorities.get(base_name, 999)
                chat_models.append({
                    "id": model_id,
                    "name": model_id,
                    "priority": priority
                })

        # Sort by priority
        chat_models.sort(key=lambda x: (x["priority"], x["id"]))

        # Remove priority from response
        for model in chat_models:
            del model["priority"]

        logger.info(f"Fetched {len(chat_models)} OpenAI models from API")

        return {
            "models": chat_models if chat_models else [
                {"id": "gpt-4o", "name": "GPT-4o (Latest, Most Capable)"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Fast & Affordable)"},
                {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
            ],
            "source": "api" if chat_models else "default"
        }

    except Exception as e:
        logger.warning(f"Error fetching OpenAI models: {e}, using defaults")
        # Return default list on error
        return {
            "models": [
                {"id": "gpt-4o", "name": "GPT-4o (Latest, Most Capable)"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Fast & Affordable)"},
                {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
            ],
            "source": "default"
        }


@app.post("/api/settings/test")
async def test_credentials(data: CredentialTest):
    """Test API credentials using provided values or saved values from database"""
    try:
        if data.credential_type == 'openai':
            # Get API key from database or use provided value
            all_settings = settings_manager.get_all_settings(mask_secrets=False)
            saved_api_key = all_settings.get('OPENAI_API_KEY', {}).get('value', '')

            # Use provided value or fall back to database
            api_key = data.test_value if data.test_value else saved_api_key
            api_key = api_key.strip() if api_key else ''

            if not api_key:
                return {
                    "success": False,
                    "message": "❌ No OpenAI API key provided. Please enter your API key or save it first."
                }

            success, message = test_openai_key(api_key)
            logger.info(f"OpenAI API test: {message}")

            return {
                "success": success,
                "message": message
            }

        elif data.credential_type == 'smtp':
            # Get SMTP credentials from database or use provided values
            all_settings = settings_manager.get_all_settings(mask_secrets=False)
            saved_smtp_user = all_settings.get('SMTP_USER', {}).get('value', '')
            saved_smtp_pass = all_settings.get('SMTP_PASS', {}).get('value', '')

            logger.debug(f"SMTP test request - test_user: {data.test_user}, test_pass: {'[present]' if data.test_pass else '[empty]'}")

            smtp_user = data.test_user if data.test_user else saved_smtp_user
            smtp_pass = data.test_pass if data.test_pass else saved_smtp_pass
            smtp_user = smtp_user.strip() if smtp_user else ''
            smtp_pass = smtp_pass.strip() if smtp_pass else ''

            logger.debug(f"SMTP test - Using user: {smtp_user}, pass: {'[present]' if smtp_pass else '[empty]'}")

            if not smtp_user or not smtp_pass:
                missing = []
                if not smtp_user:
                    missing.append("SMTP User")
                if not smtp_pass:
                    missing.append("Gmail App Password")

                return {
                    "success": False,
                    "message": f"❌ Missing credentials: {', '.join(missing)}. Please fill in the fields or save them first."
                }

            success, message = test_smtp_credentials(smtp_user, smtp_pass)
            logger.info(f"SMTP test: {message}")

            return {
                "success": success,
                "message": message
            }

        else:
            raise HTTPException(status_code=400, detail="Invalid credential type")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings/send-test-email")
async def send_test_email(request: Request):
    """
    Send a test email to the configured TARGET_EMAIL address.
    This tests SMTP connection, authentication, AND email delivery.

    Accepts optional parameters from request body to test unsaved settings:
    - target_email: Email address to send test to
    - smtp_user: SMTP username
    - smtp_pass: SMTP password
    - smtp_server: SMTP server (defaults to smtp.gmail.com)
    - smtp_port: SMTP port (defaults to 587)

    If parameters not provided, falls back to database settings.

    Returns:
        dict: Success status and message
    """
    import smtplib
    from datetime import datetime
    from src.core.email_sender import EmailSender

    try:
        # Try to get settings from request body first
        body = await request.json() if request.headers.get('content-type') == 'application/json' else {}

        # Use provided values or fall back to database
        if body:
            target_email = body.get('target_email')
            smtp_user = body.get('smtp_user')
            smtp_pass = body.get('smtp_pass')
            smtp_server = body.get('smtp_server', 'smtp.gmail.com')
            smtp_port = body.get('smtp_port', 587)
        else:
            # Get email settings from database
            all_settings = settings_manager.get_all_settings(mask_secrets=False)
            target_email = all_settings.get('TARGET_EMAIL', {}).get('value')
            smtp_user = all_settings.get('SMTP_USER', {}).get('value')
            smtp_pass = all_settings.get('SMTP_PASS', {}).get('value')
            smtp_server = 'smtp.gmail.com'
            smtp_port = 587

        # Validate required settings
        if not target_email:
            return {"success": False, "message": "❌ TARGET_EMAIL not configured"}
        if not smtp_user:
            return {"success": False, "message": "❌ SMTP_USER not configured"}
        if not smtp_pass:
            return {"success": False, "message": "❌ SMTP_PASS not configured"}

        # Note: We don't validate password length here - let the SMTP server validate credentials
        # Gmail app passwords are typically 16 chars, but other providers may differ

        # Create test email content
        test_video = {
            'title': 'YAYS Email Configuration Test',
            'id': 'test',  # EmailSender expects 'id' not 'video_id'
            'video_id': 'test',
            'url': 'https://github.com/icon3333/YAYS',
            'duration_string': 'Test',
            'view_count': 0,
            'upload_date': datetime.now().strftime('%Y-%m-%d')
        }

        test_summary = f"""YAYS - Email Target Test
========================

This is a test email from your YAYS (YouTube AI Summary) application.

If you received this email, your email configuration is working correctly!

Configuration Details:
- Target Email: {target_email}
- SMTP Server: smtp.gmail.com:587
- SMTP User: {smtp_user}

What's Next?
- Your video summaries will be delivered to this email address
- Make sure this email address is correct
- Check your spam folder if you don't receive summaries

---
Sent by YAYS - YouTube AI Summary
https://github.com/icon3333/YAYS"""

        # Send test email using existing EmailSender
        email_sender = EmailSender(smtp_user, smtp_pass, target_email)
        success = email_sender.send_email(test_video, test_summary, "YAYS System")

        if success:
            logger.info(f"Test email sent successfully to {target_email}")
            return {
                "success": True,
                "message": f"✅ Test email sent successfully to {target_email} - Check your inbox!"
            }
        else:
            logger.error("Test email failed - EmailSender returned False")
            return {
                "success": False,
                "message": "❌ Failed to send test email. Check logs for details."
            }

    except smtplib.SMTPAuthenticationError:
        logger.error("Test email failed: SMTP authentication error")
        return {
            "success": False,
            "message": "❌ Invalid email or password"
        }

    except smtplib.SMTPException as e:
        logger.error(f"Test email failed: SMTP error - {str(e)}")
        return {
            "success": False,
            "message": f"❌ SMTP error: {str(e)[:100]}"
        }

    except Exception as e:
        logger.error(f"Test email failed: {str(e)}")
        return {
            "success": False,
            "message": f"❌ Connection failed: {str(e)[:100]}"
        }


# ============================================================================
# RESET API ENDPOINTS
# ============================================================================

@app.post("/api/reset/settings")
async def reset_settings():
    """
    Reset Settings: Reset all settings and AI prompt to defaults.
    Channels and feed history are preserved.
    """
    try:
        logger.info("Resetting settings and prompt to defaults")

        # Reset prompt to default
        config_manager.reset_prompt_to_default()

        # Reset all settings in config.txt to defaults
        config_manager.reset_all_settings()

        logger.info("Settings and prompt reset complete")

        return {
            "success": True,
            "message": "✅ Successfully reset all settings and AI prompt to defaults"
        }
    except Exception as e:
        logger.error(f"Error resetting settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset/youtube-data")
async def reset_youtube_data():
    """
    Reset YouTube Data: Delete all channels and feed history.
    Settings and prompts are preserved.
    """
    try:
        logger.info("Resetting YouTube data (channels + feed)")

        # Get current counts before deletion
        channels, _, _ = config_manager.get_channels()
        channel_count = len(channels)

        # Delete all videos from database
        video_count = video_db.reset_all_data()

        # Clear channels from config
        config_manager.set_channels([])

        logger.info(f"Reset complete: Deleted {video_count} videos and {channel_count} channels")

        return {
            "success": True,
            "message": f"✅ Successfully deleted {video_count} videos and {channel_count} channels",
            "videos_deleted": video_count,
            "channels_deleted": channel_count
        }
    except Exception as e:
        logger.error(f"Error resetting YouTube data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset/feed-history")
async def reset_feed_history():
    """
    Reset Feed History: Delete all processed videos.
    Channels and settings are preserved.
    """
    try:
        logger.info("Resetting feed history")

        # Delete all videos from database
        video_count = video_db.reset_all_data()

        logger.info(f"Reset complete: Deleted {video_count} videos")

        return {
            "success": True,
            "message": f"✅ Successfully deleted {video_count} videos from feed history",
            "videos_deleted": video_count
        }
    except Exception as e:
        logger.error(f"Error resetting feed history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset/complete")
async def reset_complete_app():
    """
    Reset Complete App: Delete all data and reset settings.
    This includes channels, feed history, and resets all settings and prompts to defaults.
    """
    try:
        logger.info("Resetting complete application")

        # Get current counts before deletion
        channels, _, _ = config_manager.get_channels()
        channel_count = len(channels)

        # Delete all videos from database
        video_count = video_db.reset_all_data()

        # Clear channels from config
        config_manager.set_channels([])

        # Reset prompt to default
        config_manager.reset_prompt_to_default()

        # Reset all settings in config.txt to defaults
        config_manager.reset_all_settings()

        logger.info(f"Complete reset: Deleted {video_count} videos, {channel_count} channels, reset settings and prompt")

        return {
            "success": True,
            "message": f"✅ Successfully reset application: {video_count} videos deleted, {channel_count} channels deleted, settings and prompt reset to defaults",
            "videos_deleted": video_count,
            "channels_deleted": channel_count
        }
    except Exception as e:
        logger.error(f"Error resetting application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CHANNEL STATS & FEED API ENDPOINTS
# ============================================================================

@app.get("/api/stats/channels")
async def get_channel_stats():
    """Get statistics for all channels"""
    try:
        # Get all channel stats from database
        stats = video_db.get_all_channel_stats()

        # Get global stats
        global_stats = video_db.get_global_stats()

        logger.info(f"Retrieved stats for {len(stats)} channels")

        return {
            "channels": stats,
            "global": global_stats
        }

    except Exception as e:
        logger.error(f"Error getting channel stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/channel/{channel_id}")
async def get_single_channel_stats(channel_id: str):
    """Get statistics for a specific channel"""
    try:
        stats = video_db.get_channel_stats(channel_id)

        logger.info(f"Retrieved stats for channel {channel_id}")

        return stats

    except Exception as e:
        logger.error(f"Error getting channel stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/videos/feed")
async def get_videos_feed(
    channel_id: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    order_by: str = 'recent'
):
    """
    Get processed videos feed with pagination

    Parameters:
    - channel_id: Filter by channel (optional)
    - source_type: Filter by source type (e.g., 'via_manual') (optional)
    - limit: Number of videos per page (default 25)
    - offset: Pagination offset (default 0)
    - order_by: Sort order - 'recent', 'oldest', 'channel' (default 'recent')
    """
    try:
        # Validate limit
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")

        # Get videos
        videos = video_db.get_processed_videos(
            channel_id=channel_id,
            source_type=source_type,
            limit=limit,
            offset=offset,
            order_by=order_by
        )

        # Get total count for pagination
        total_count = video_db.get_total_count(channel_id=channel_id, source_type=source_type)

        logger.info(f"Retrieved {len(videos)} videos (offset {offset}, total {total_count})")

        return {
            "videos": videos,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total_count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting videos feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/videos/{video_id}")
async def get_video_details(video_id: str):
    """Get full details for a single video including summary"""
    try:
        video = video_db.get_video_by_id(video_id)

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        return video

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting video details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/videos/{video_id}/logs")
async def get_video_logs(video_id: str, lines: int = 800, context: int = 3):
    """
    Return relevant log lines for a single video from summarizer logs.

    Params:
    - lines: max number of lines to scan from the end of the log (default 800)
    - context: extra context lines before/after each match (default 3)
    """
    try:
        # Validate video exists and get metadata for better matching
        video = video_db.get_video_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        log_path = Path('logs') / 'summarizer.log'
        if not log_path.exists():
            return JSONResponse(
                status_code=200,
                content={
                    "video_id": video_id,
                    "title": video.get('title'),
                    "status": video.get('processing_status'),
                    "lines": [],
                    "message": "No summarizer.log found yet.",
                }
            )

        # Read and scan last N lines for matches
        with log_path.open('r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()

        # Limit scanning to tail portion for performance
        tail = all_lines[-max(0, lines):]

        # Build match tokens: prefer video_id; also include a compact title token
        tokens: List[str] = [video_id]
        title = (video.get('title') or '').strip()
        if title:
            # Use first 25 characters to match truncated title logs like "▶️ <title>..."
            tokens.append(title[:25])

        match_indices: List[int] = []
        lowered = [ln.lower() for ln in tail]
        token_lowers = [t.lower() for t in tokens if t]

        for i, ln in enumerate(lowered):
            if any(tok in ln for tok in token_lowers):
                match_indices.append(i)

        # If no matches, check if we should show general logs for context
        if not match_indices:
            # For pending/processing/failed videos, show recent initialization/error logs
            status = video.get('processing_status', '')
            if status in ['pending', 'processing', 'failed_transcript', 'failed_ai', 'failed_email']:
                # Show last 50 lines of general logs for context (errors, initialization, etc.)
                recent_context = min(50, len(tail))
                context_lines = [ln.rstrip('\n') for ln in tail[-recent_context:]]
                context_lines.reverse()  # Newest first

                return JSONResponse(
                    status_code=200,
                    content={
                        "video_id": video_id,
                        "title": video.get('title'),
                        "status": status,
                        "lines": context_lines,
                        "message": f"No video-specific logs found yet. Showing recent general logs for context (status: {status})",
                    }
                )
            else:
                # For completed videos, empty logs means something went wrong
                return JSONResponse(
                    status_code=200,
                    content={
                        "video_id": video_id,
                        "title": video.get('title'),
                        "status": status,
                        "lines": [],
                        "message": "No matching log lines found for this video in the recent log tail.",
                    }
                )

        # Collect context windows and de-duplicate while preserving order
        seen: set = set()
        collected: List[str] = []
        for idx in match_indices:
            start = max(0, idx - max(0, context))
            end = min(len(tail), idx + max(0, context) + 1)
            for j in range(start, end):
                # Use absolute position in tail to avoid duplicates
                key = (j, tail[j])
                if key in seen:
                    continue
                seen.add(key)
                collected.append(tail[j].rstrip('\n'))

        # Reverse the order so newest logs appear first
        collected.reverse()

        return JSONResponse(
            status_code=200,
            content={
                "video_id": video_id,
                "title": video.get('title'),
                "status": video.get('processing_status'),
                "lines": collected,
                "message": None,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading logs for {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/videos/{video_id}/retry")
async def retry_video_processing(video_id: str):
    """
    Retry processing for a failed video
    Resets status to 'pending' and triggers reprocessing
    """
    try:
        # Check if video exists
        video = video_db.get_video_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Reset video status to pending
        video_db.reset_video_status(video_id)
        logger.info(f"Reset video {video_id} to pending status")

        # Trigger immediate processing in background using the same Python interpreter
        try:
            subprocess.Popen([sys.executable, 'process_videos.py'])
            logger.info("Started background processing for retry")
        except Exception as e:
            logger.error(f"Failed to start background processing: {e}")

        return {
            "status": "success",
            "message": "Video queued for reprocessing"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying video {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/videos/{video_id}/stop")
async def stop_video_processing(video_id: str):
    """
    Stop processing for a video by marking it as failed_stopped
    This allows user to cancel stuck or unwanted processing
    """
    try:
        # Check if video exists
        video = video_db.get_video_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Only stop if currently pending or processing
        current_status = video.get('processing_status')
        stoppable_statuses = ['pending', 'processing', 'fetching_metadata', 'fetching_transcript', 'generating_summary']

        if current_status not in stoppable_statuses:
            return {
                "status": "info",
                "message": f"Video cannot be stopped (current status: {current_status})"
            }

        # Mark as stopped
        video_db.update_video_processing(
            video_id,
            status='failed_stopped',
            error_message='Processing stopped by user'
        )
        logger.info(f"Stopped processing for video {video_id} (was: {current_status})")

        return {
            "status": "success",
            "message": "Processing stopped"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping video {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/videos/{video_id}/force-retry")
async def force_retry_video(video_id: str):
    """
    Force retry a permanently failed video by resetting retry count
    """
    try:
        # Check if video exists
        video = video_db.get_video_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Reset retry count and status
        video_db.update_video_processing(
            video_id,
            status='pending',
            retry_count=0,
            error_message=None
        )
        logger.info(f"Force retry for video {video_id} - reset retry count")

        # Trigger immediate processing
        try:
            subprocess.Popen([sys.executable, 'process_videos.py'])
            logger.info("Started background processing for force retry")
        except Exception as e:
            logger.error(f"Failed to start background processing: {e}")

        return {
            "status": "success",
            "message": "Video queued for force retry"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error force retrying video {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    """
    Delete a video from the database (typically used for manually added videos)
    """
    try:
        # Check if video exists
        video = video_db.get_video_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Delete the video
        success = video_db.delete_video(video_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete video")

        logger.info(f"Deleted video {video_id}: {video.get('title', 'Unknown')}")

        return {
            "status": "success",
            "message": "Video deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting video {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/videos/process-now")
async def process_videos_now():
    """
    Manually trigger video processing for all channels
    Runs process_videos.py in background
    """
    try:
        # Run process_videos.py as subprocess (non-blocking)
        # Use sys.executable to ensure we use the same Python interpreter (venv)
        # Use absolute path to ensure it works regardless of working directory
        script_path = Path(__file__).parent.parent.parent / 'process_videos.py'
        subprocess.Popen([sys.executable, str(script_path)])
        logger.info("Manual processing triggered")

        return {
            "status": "success",
            "message": "Video processing started in background"
        }

    except Exception as e:
        logger.error(f"Error starting manual processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def extract_video_id_from_url(url: str) -> Optional[str]:
    """
    Extract video ID from various YouTube URL formats
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID (will be rejected later if SKIP_SHORTS is true)
    - VIDEO_ID (if exactly 11 characters)
    """
    url = url.strip()

    # Direct video ID (11 characters, alphanumeric with dashes/underscores)
    if len(url) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url

    # youtu.be/VIDEO_ID
    match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if match:
        return match.group(1)

    # youtube.com/watch?v=VIDEO_ID
    match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
    if match:
        return match.group(1)

    # youtube.com/shorts/VIDEO_ID
    match = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', url)
    if match:
        return match.group(1)

    return None


@app.post("/api/videos/add-single")
async def add_single_video(data: SingleVideoAdd):
    """
    Add a single video manually by URL

    Process:
    1. Extract video ID from URL
    2. Get video metadata (title, channel, duration, etc.)
    3. Validate: not a short, not already processed
    4. Add to database with source_type='via_manual'
    5. Trigger background processing

    Returns:
    - Success: video details
    - Error: error message
    """
    try:
        # Extract video ID from URL
        video_id = extract_video_id_from_url(data.video_url)

        if not video_id:
            raise HTTPException(
                status_code=400,
                detail="Could not extract video ID from URL. Please provide a valid YouTube video URL."
            )

        logger.info(f"Adding single video manually: {video_id}")

        # Check if already processed
        if video_db.is_processed(video_id):
            raise HTTPException(
                status_code=400,
                detail="Video already processed. Check your feed for the existing summary."
            )

        # Add video to database immediately with minimal metadata
        # Background processor will fetch full metadata (avoids blocking web request with rate limit sleeps)
        success = video_db.add_video(
            video_id=video_id,
            channel_id='unknown',
            title=f"Video {video_id}",
            channel_name='Unknown Channel',
            duration_seconds=None,
            view_count=None,
            upload_date=None,
            processing_status='pending',
            source_type='via_manual'
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to add video to database. It may already exist."
            )

        logger.info(f"Added manual video {video_id} to queue for processing")

        # Trigger immediate background processing
        try:
            subprocess.Popen([sys.executable, 'process_videos.py'])
            logger.info("Started background processing for manual video")
        except Exception as e:
            logger.error(f"Failed to start background processing: {e}")

        return {
            "status": "success",
            "message": "Video queued for processing!",
            "video": {
                "id": video_id,
                "title": f"Video {video_id}",
                "channel_name": "Unknown Channel",
                "duration_formatted": "Unknown",
                "processing_status": "pending"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding single video: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add video: {str(e)}")


# ============================================================================
# EXPORT API ENDPOINTS
# ============================================================================

@app.get("/api/export/feed")
async def export_feed(format: str = "json"):
    """
    Export Feed level data (channels + videos).

    Parameters:
    - format: 'json' or 'csv' (default: 'json')

    Returns:
    - StreamingResponse with downloadable export file
    """
    try:
        if format not in ("json", "csv"):
            raise HTTPException(
                status_code=400,
                detail="Invalid format parameter. Must be 'json' or 'csv'"
            )

        if format == "json":
            # Export Feed as JSON
            data = export_manager.export_feed_json()
            filename = export_manager.generate_export_filename("feed_export", "json")

            # Convert to JSON string (pretty-printed)
            json_str = json.dumps(data, indent=2, ensure_ascii=False)

            # Return as downloadable file
            return StreamingResponse(
                io.BytesIO(json_str.encode('utf-8')),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                }
            )

        else:  # format == "csv"
            # Export videos as CSV
            csv_content = export_manager.export_videos_csv()
            filename = export_manager.generate_export_filename("videos", "csv")

            # Return as downloadable file
            return StreamingResponse(
                io.BytesIO(csv_content.encode('utf-8-sig')),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export feed failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )


@app.get("/api/export/backup")
async def export_backup():
    """
    Export Complete Backup (channels + videos + settings + AI prompt).

    Returns:
    - StreamingResponse with downloadable JSON backup file
    """
    try:
        # Export Complete Backup
        data = export_manager.export_complete_backup_json()
        filename = export_manager.generate_export_filename("full_backup", "json")

        # Convert to JSON string (pretty-printed)
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        # Return as downloadable file
        return StreamingResponse(
            io.BytesIO(json_str.encode('utf-8')),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Export backup failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )


# ============================================================================
# IMPORT API ENDPOINTS
# ============================================================================

@app.post("/api/import/validate")
async def validate_import(file: UploadFile = File(...)):
    """
    Validate import file and generate preview of changes.

    Parameters:
    - file: Uploaded JSON file

    Returns:
    - Validation result with preview
    """
    try:
        # Check file type
        if not file.filename.endswith('.json'):
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "errors": ["File must be a JSON file"],
                    "warnings": [],
                    "preview": None
                }
            )

        # Read file content
        content = await file.read()

        # Check file size (50 MB limit)
        if len(content) > import_manager.MAX_FILE_SIZE_BYTES:
            size_mb = len(content) / (1024 * 1024)
            return JSONResponse(
                status_code=413,
                content={
                    "valid": False,
                    "errors": [f"File too large ({size_mb:.1f} MB). Maximum size is 50 MB."],
                    "warnings": [],
                    "preview": None
                }
            )

        # Parse JSON
        try:
            data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            return JSONResponse(
                status_code=200,
                content={
                    "valid": False,
                    "errors": [f"Invalid JSON syntax: {str(e)}"],
                    "warnings": [],
                    "preview": None
                }
            )

        # Validate file structure
        validation_result = import_manager.validate_import_file(data)

        if not validation_result.valid:
            return JSONResponse(
                status_code=200,
                content={
                    "valid": False,
                    "errors": validation_result.errors,
                    "warnings": validation_result.warnings,
                    "preview": None
                }
            )

        # Generate preview
        preview = import_manager.preview_import(data)

        return JSONResponse(
            status_code=200,
            content={
                "valid": True,
                "errors": [],
                "warnings": validation_result.warnings,
                "preview": {
                    "channels_new": preview.channels_new,
                    "channels_existing": preview.channels_existing,
                    "videos_new": preview.videos_new,
                    "videos_duplicate": preview.videos_duplicate,
                    "settings_changed": preview.settings_changed,
                    "settings_details": preview.settings_details,
                    "total_size_mb": preview.total_size_mb
                }
            }
        )

    except Exception as e:
        logger.error(f"Import validation failed: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
                "preview": None
            }
        )


@app.post("/api/import/execute")
async def execute_import(file: UploadFile = File(...)):
    """
    Execute import operation with rollback safety.

    Parameters:
    - file: Uploaded JSON file (must be validated first)

    Returns:
    - Import result with counts
    """
    try:
        # Check file type
        if not file.filename.endswith('.json'):
            raise HTTPException(
                status_code=400,
                detail="File must be a JSON file"
            )

        # Read file content
        content = await file.read()

        # Check file size
        if len(content) > import_manager.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="File too large (max 50 MB)"
            )

        # Parse JSON
        try:
            data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid JSON syntax: {str(e)}"
            )

        # Validate before import
        validation_result = import_manager.validate_import_file(data)
        if not validation_result.valid:
            raise HTTPException(
                status_code=400,
                detail=f"Validation failed: {'; '.join(validation_result.errors)}"
            )

        # Execute import
        import_result = import_manager.import_data(data)

        if not import_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Import failed: {'; '.join(import_result.errors)}"
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Import successful: {import_result.channels_added} channels, {import_result.videos_added} videos, {import_result.settings_updated} settings",
                "channels_added": import_result.channels_added,
                "videos_added": import_result.videos_added,
                "settings_updated": import_result.settings_updated
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import execution failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {str(e)}"
        )


# ===== LOGS API ENDPOINTS =====

@app.get("/api/logs/list")
async def list_logs():
    """List available log sources with metadata"""
    from datetime import datetime

    logs_dir = Path('logs')
    logs_config = [
        {'name': 'web', 'display_name': 'Web Container', 'file': 'web.log'},
        {'name': 'summarizer', 'display_name': 'Summarizer Container', 'file': 'summarizer.log'}
    ]

    result = []
    for config in logs_config:
        file_path = logs_dir / config['file']
        exists = file_path.exists()

        log_info = {
            'name': config['name'],
            'display_name': config['display_name'],
            'file_path': str(file_path),
            'exists': exists
        }

        if exists:
            stat = file_path.stat()
            log_info['size_bytes'] = stat.st_size
            log_info['last_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat() + 'Z'
        else:
            log_info['size_bytes'] = 0
            log_info['last_modified'] = None

        result.append(log_info)

    return {'logs': result}


@app.get("/api/logs/{log_name}")
async def get_logs(log_name: str, lines: int = 1000, offset: int = 0):
    """Retrieve log content with redaction"""
    from datetime import datetime
    from src.utils.log_redactor import redact_sensitive_data
    from src.utils.tail_reader import read_tail_lines

    # Validate log name
    valid_logs = {'web', 'summarizer'}
    if log_name not in valid_logs:
        raise HTTPException(400, f"Invalid log name: {log_name}. Must be 'web' or 'summarizer'")

    # Validate parameters
    lines = max(1, min(lines, 5000))
    offset = max(0, offset)

    file_path = Path('logs') / f'{log_name}.log'

    if not file_path.exists():
        return {
            'log_name': log_name,
            'content': '',
            'total_lines': 0,
            'returned_lines': 0,
            'offset': offset,
            'file_size_bytes': 0,
            'last_modified': None
        }

    try:
        # Use efficient tail reader - only reads necessary portion of file
        selected_lines = read_tail_lines(str(file_path), lines, offset)

        # Get total line count efficiently (without loading all content)
        total_lines = 0
        with open(file_path, 'rb') as f:
            total_lines = sum(1 for _ in f)

        content = ''.join(selected_lines)
        redacted_content = redact_sensitive_data(content)

        stat = file_path.stat()

        return {
            'log_name': log_name,
            'content': redacted_content,
            'total_lines': total_lines,
            'returned_lines': len(selected_lines),
            'offset': offset,
            'file_size_bytes': stat.st_size,
            'last_modified': datetime.fromtimestamp(stat.st_mtime).isoformat() + 'Z'
        }

    except Exception as e:
        logger.error(f"Failed to read log file {file_path}: {e}")
        raise HTTPException(500, f"Failed to read log file: {str(e)}")


@app.get("/api/logs/{log_name}/download")
async def download_logs(log_name: str):
    """Download full log file with redaction"""
    from datetime import datetime
    from src.utils.log_redactor import redact_sensitive_data

    valid_logs = {'web', 'summarizer'}
    if log_name not in valid_logs:
        raise HTTPException(400, f"Invalid log name: {log_name}")

    file_path = Path('logs') / f'{log_name}.log'

    if not file_path.exists():
        raise HTTPException(404, f"Log file not found: {file_path}")

    # Check file size to prevent OOM issues
    MAX_DOWNLOAD_SIZE_MB = 50
    MAX_DOWNLOAD_SIZE_BYTES = MAX_DOWNLOAD_SIZE_MB * 1024 * 1024

    file_size = file_path.stat().st_size
    if file_size > MAX_DOWNLOAD_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise HTTPException(
            413,
            f"Log file is too large to download ({size_mb:.1f}MB). "
            f"Maximum size is {MAX_DOWNLOAD_SIZE_MB}MB. "
            f"Use the logs viewer with pagination instead."
        )

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        redacted_content = redact_sensitive_data(content)

        timestamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
        filename = f"yays-{log_name}-{timestamp}.log"

        return StreamingResponse(
            io.StringIO(redacted_content),
            media_type='text/plain; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Failed to download log file {file_path}: {e}")
        raise HTTPException(500, f"Failed to download log file: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting YouTube Summarizer Web UI (Modern Minimalist)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
