"""
Log Cleanup Utility

Manages automatic deletion of old log files based on retention policy.
Preserves active log files while cleaning up rotated backups.
"""

from pathlib import Path
from datetime import datetime, timedelta
import logging

logger = logging.getLogger('log_cleanup')


def cleanup_old_logs(retention_days: int, logs_dir: str = 'logs'):
    """
    Delete log files older than retention_days.

    Args:
        retention_days: Delete files older than this many days
        logs_dir: Directory containing log files (default: 'logs')
    """
    if not isinstance(retention_days, int) or retention_days < 1:
        logger.error(f"Invalid retention_days value: {retention_days}. Must be a positive integer.")
        return

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    logs_path = Path(logs_dir)

    if not logs_path.exists():
        logger.warning(f"Logs directory does not exist: {logs_dir}")
        return

    if not logs_path.is_dir():
        logger.error(f"Logs path is not a directory: {logs_dir}")
        return

    # Protected files (never delete currently active logs)
    protected_files = {'web.log', 'summarizer.log'}

    deleted_count = 0
    deleted_size = 0
    errors = []

    # Find all .log* files (includes rotated backups like .log.1, .log.2)
    for log_file in logs_path.glob('*.log*'):
        # Skip protected files
        if log_file.name in protected_files:
            continue

        try:
            # Check file modification time
            file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

            if file_mtime < cutoff_date:
                file_size = log_file.stat().st_size
                log_file.unlink()
                deleted_count += 1
                deleted_size += file_size
                logger.info(f"Deleted old log file: {log_file.name} (age: {(datetime.now() - file_mtime).days} days)")
        except PermissionError as e:
            error_msg = f"Permission denied deleting {log_file.name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"Failed to delete log file {log_file.name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    if deleted_count > 0:
        logger.info(f"Log cleanup completed: deleted {deleted_count} files ({deleted_size / 1024 / 1024:.2f} MB) older than {retention_days} days")
    else:
        logger.debug(f"Log cleanup completed: no files older than {retention_days} days")

    if errors:
        logger.warning(f"Log cleanup encountered {len(errors)} errors during cleanup")


if __name__ == '__main__':
    # Test the cleanup (dry run with logging)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    print("Testing log cleanup (dry run)...")
    cleanup_old_logs(retention_days=7, logs_dir='logs')
