import os
import subprocess
import logging
import psutil
import shutil
import tempfile
from datetime import datetime, timedelta
from config import LOGS_DIR, SCRIPTS_DIR

logger = logging.getLogger(__name__)

MAX_LOG_SIZE_MB = 1
LINES_TO_KEEP = 100

def clean_pip_cache():
    """Removes cached pip downloads to free up significant disk space."""
    try:
        logger.info("Running pip cache purge to free disk space...")
        res = subprocess.run(["python", "-m", "pip", "cache", "purge"], capture_output=True, text=True)
        if res.returncode == 0:
            logger.info(f"pip cache cleared: {res.stdout.strip()}")
        else:
            logger.warning(f"Failed to clear pip cache: {res.stderr.strip()}")
    except Exception as e:
        logger.error(f"Error purging pip cache: {e}")


def clean_temp_files():
    """Removes temporary files from /tmp and system temp directory."""
    freed = 0
    try:
        tmp_dir = tempfile.gettempdir()
        for item in os.listdir(tmp_dir):
            item_path = os.path.join(tmp_dir, item)
            try:
                size = os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    freed += size
                elif os.path.isdir(item_path):
                    dir_size = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, dn, fn in os.walk(item_path)
                        for f in fn
                    )
                    shutil.rmtree(item_path, ignore_errors=True)
                    freed += dir_size
            except Exception:
                pass
        logger.info(f"Temp files cleaned: freed {freed // 1024} KB")
    except Exception as e:
        logger.error(f"Error cleaning temp files: {e}")


def clean_pycache():
    """Removes __pycache__ directories to free disk space."""
    freed = 0
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for root, dirs, files in os.walk(base):
        if "__pycache__" in dirs:
            cache_path = os.path.join(root, "__pycache__")
            try:
                size = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, dn, fn in os.walk(cache_path)
                    for f in fn
                )
                shutil.rmtree(cache_path, ignore_errors=True)
                freed += size
            except Exception:
                pass
    if freed > 0:
        logger.info(f"__pycache__ cleaned: freed {freed // 1024} KB")


def clean_old_logs():
    """Removes log files older than 3 days."""
    cutoff = datetime.now() - timedelta(days=3)
    removed = 0
    for root, dirs, files in os.walk(LOGS_DIR):
        for file in files:
            if file.endswith(".log"):
                filepath = os.path.join(root, file)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < cutoff:
                        os.remove(filepath)
                        removed += 1
                except Exception:
                    pass
    if removed:
        logger.info(f"Removed {removed} old log files (>3 days)")


def shrink_log_files():
    """Scans all log files and truncates the ones exceeding the size limit."""
    logger.info("Scanning for oversized log files...")
    bytes_limit = MAX_LOG_SIZE_MB * 1024 * 1024
    shrunk_count = 0
    freed_bytes = 0

    for root, dirs, files in os.walk(LOGS_DIR):
        for file in files:
            if file.endswith(".log"):
                filepath = os.path.join(root, file)
                try:
                    size = os.path.getsize(filepath)
                    if size > bytes_limit:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()
                        keep = lines[-LINES_TO_KEEP:] if len(lines) > LINES_TO_KEEP else lines
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.writelines(keep)
                        new_size = os.path.getsize(filepath)
                        freed_bytes += (size - new_size)
                        shrunk_count += 1
                except Exception as e:
                    logger.error(f"Error shrinking log file {filepath}: {e}")

    if shrunk_count > 0:
        logger.info(f"Shrunk {shrunk_count} log files, freeing {freed_bytes // (1024 * 1024)} MB")
    else:
        logger.info("No oversized log files found.")


def log_disk_usage():
    """Log current disk usage stats."""
    try:
        usage = psutil.disk_usage("/")
        logger.info(
            f"Disk usage: {usage.used // (1024**3):.1f}GB used / "
            f"{usage.total // (1024**3):.1f}GB total "
            f"({usage.percent}% full)"
        )
        ram = psutil.virtual_memory()
        logger.info(
            f"RAM usage: {ram.used // (1024**2)}MB used / "
            f"{ram.total // (1024**2)}MB total "
            f"({ram.percent}% full)"
        )
    except Exception as e:
        logger.error(f"Error logging disk usage: {e}")


async def run_system_cleanup(context=None):
    """
    Main job function called by job_queue every 2 hours.
    Cleans logs, temp files, pip cache, pycache, and kills orphans.
    """
    logger.info("=== STARTING PERIODIC SYSTEM CLEANUP ===")

    log_disk_usage()

    # 1. Clean Pip cache
    clean_pip_cache()

    # 2. Shrink log files
    shrink_log_files()

    # 3. Remove old logs (>3 days)
    clean_old_logs()

    # 4. Clean temp files
    clean_temp_files()

    # 5. Clean __pycache__
    clean_pycache()

    # 6. Clean zombies
    from runner import cleanup_zombie_processes
    cleanup_zombie_processes()

    log_disk_usage()
    logger.info("=== SYSTEM CLEANUP DONE ===")


async def check_expiring_subscriptions(context):
    """
    Job يشتغل يومياً — يبعت إشعار للمستخدمين اللي اشتراكهم هينتهي خلال يوم.
    """
    from database import get_session, User

    now = datetime.utcnow()
    warning_threshold = now + timedelta(days=1)

    with get_session() as s:
        expiring = s.query(User).filter(
            User.subscription_expiry != None,
            User.subscription_expiry > now,
            User.subscription_expiry <= warning_threshold,
            User.is_banned == False,
        ).all()
        user_data = [(u.id, u.subscription_expiry) for u in expiring]

    for user_id, expiry in user_data:
        remaining = expiry - now
        hours = int(remaining.total_seconds() // 3600)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ تنبيه: اشتراكك سينتهي خلال {hours} ساعة تقريباً.\n"
                    "تواصل مع المالك لتجديد الاشتراك."
                )
            )
            logger.info(f"Sent expiry warning to user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to notify user {user_id} about expiry: {e}")
