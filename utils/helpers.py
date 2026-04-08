"""
Shared helper utilities.
"""
import os
import logging
import psutil
from datetime import datetime
from config import SCRIPTS_DIR, LOGS_DIR

logger = logging.getLogger(__name__)


def get_user_scripts_dir(user_id: int) -> str:
    path = os.path.join(SCRIPTS_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_log_path(user_id: int, file_name: str) -> str:
    base = os.path.splitext(file_name)[0]
    path = os.path.join(LOGS_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, f"{base}.log")


def read_log_tail(log_path: str, lines: int = 50) -> str:
    if not os.path.exists(log_path):
        return "📭 لا يوجد سجل بعد."
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return "".join(tail) or "📭 السجل فارغ."
    except Exception as e:
        return f"❌ خطأ في قراءة السجل: {e}"


def clear_log(log_path: str):
    try:
        open(log_path, "w").close()
    except Exception as e:
        logger.error(f"Error clearing log {log_path}: {e}")


def kill_process_tree(pid: int):
    """Kill a process and all its children."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs([parent] + children, timeout=3)
        logger.info(f"Killed process tree for PID {pid}")
    except psutil.NoSuchProcess:
        logger.warning(f"PID {pid} already dead.")
    except Exception as e:
        logger.error(f"Error killing PID {pid}: {e}")


def format_uptime(start_time: datetime) -> str:
    if not start_time:
        return "—"
    delta = datetime.utcnow() - start_time
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s"
