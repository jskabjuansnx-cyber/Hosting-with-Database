import os
import subprocess
import logging
import psutil
from config import LOGS_DIR

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
                        # Read the last N lines and write them back
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
        logger.info(f"Shrunk {shrunk_count} log files, freeing {freed_bytes // (1024 * 1024)} MB of disk space.")
    else:
        logger.info("No oversized log files found.")


async def run_system_cleanup(context=None):
    """
    Main job function called by job_queue every 5 hours.
    Cleans logs, clears pip cache, and kills orphans.
    """
    logger.info("=== STARTING PERIODIC SYSTEM CLEANUP ===")
    
    # 1. Clean Pip cache for disk space
    clean_pip_cache()
    
    # 2. Shrink log files
    shrink_log_files()
    
    # 3. Clean zombies (memory footprint)
    from runner import cleanup_zombie_processes
    cleanup_zombie_processes()
    
    logger.info("=== SYSTEM CLEANUP DONE ===")
