"""Summarizer loop — replaces start_summarizer.sh."""
import subprocess
import sys
import time
from datetime import datetime, timedelta


def get_check_interval_seconds():
    """Read CHECK_INTERVAL_HOURS from database settings."""
    try:
        sys.path.insert(0, "/app/src")
        from managers.settings_manager import SettingsManager
        settings_mgr = SettingsManager(db_path="/app/data/videos.db")
        interval_hours = settings_mgr.get_setting("CHECK_INTERVAL_HOURS")
        if interval_hours and interval_hours.isdigit():
            return int(interval_hours) * 3600
    except Exception as e:
        print(f"Error reading interval from database: {e}", file=sys.stderr)
    return 14400  # default 4 hours


def main():
    print("Starting YAYS Summarizer Service")
    print("=" * 34)

    while True:
        interval_seconds = get_check_interval_seconds()
        interval_hours = round(interval_seconds / 3600, 2)
        now = datetime.now()

        print(f"\n{now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Check interval: {interval_hours} hours ({interval_seconds} seconds)\n")

        result = subprocess.run([sys.executable, "-u", "process_videos.py"])
        if result.returncode != 0:
            print(f"Process exited with code {result.returncode}")

        next_run = now + timedelta(seconds=interval_seconds)
        print(f"\nSleeping for {interval_hours} hours...")
        print(f"Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
