"""
Script Runner — manages launching, monitoring, and stopping user scripts.
Supports Python (.py) and JavaScript (.js) scripts.
"""
import os
import sys
import logging
import subprocess
import threading
import re
import time
from datetime import datetime
from typing import Optional

import psutil

import database as db
from config import MAX_PROCESSES, SCRIPT_TIMEOUT, TELEGRAM_MODULES
from utils.helpers import get_log_path, kill_process_tree

logger = logging.getLogger(__name__)

# ─── In-memory process registry ─────────────────────────────
# { script_id: { 'process': Popen, 'log_file': file, 'start_time': datetime } }
_processes: dict[int, dict] = {}
_lock = threading.Lock()


# ─── Public API ─────────────────────────────────────────────

def start_script(script: db.Script, notify_cb=None) -> tuple[bool, str]:
    """
    Launch a script. Returns (success, message).
    notify_cb(msg): optional callback to send status messages.
    """
    with _lock:
        if len(_processes) >= MAX_PROCESSES:
            return False, f"❌ تم الوصول للحد الأقصى من العمليات ({MAX_PROCESSES})."

        if script.id in _processes:
            return False, "⚠️ السكربت يعمل بالفعل."

        if not os.path.exists(script.file_path):
            db.set_script_stopped(script.id)
            return False, f"❌ الملف غير موجود: `{script.file_name}`"

        log_path = get_log_path(script.owner_id, script.file_name)
        try:
            log_file = open(log_path, "a", encoding="utf-8", errors="ignore")
        except Exception as e:
            return False, f"❌ فشل فتح ملف السجل: {e}"

        cmd = _build_command(script)
        if not cmd:
            log_file.close()
            return False, f"❌ نوع الملف غير مدعوم: `{script.file_type}`"

        # Auto-install missing packages
        if script.file_type == "py":
            install_result = _check_and_install_python_packages(script.file_path)
            if not install_result[0]:
                log_file.close()
                return False, install_result[1]

        try:
            # Set UTF-8 environment for the process
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            
            process = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(script.file_path),
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                env=env,
                encoding="utf-8",
                errors="ignore",
            )
        except FileNotFoundError as e:
            log_file.close()
            return False, f"❌ المفسر غير موجود: {e}"
        except Exception as e:
            log_file.close()
            return False, f"❌ خطأ في تشغيل السكربت: {e}"

        _processes[script.id] = {
            "process":    process,
            "log_file":   log_file,
            "start_time": datetime.utcnow(),
            "script":     script,
            "notify_cb":  notify_cb,
        }

    db.set_script_running(script.id, process.pid)
    logger.info(f"Started script {script.id} ({script.file_name}) PID={process.pid}")

    # Monitor thread
    threading.Thread(
        target=_monitor,
        args=(script.id,),
        daemon=True,
        name=f"monitor-{script.id}",
    ).start()

    return True, f"✅ تم تشغيل `{script.file_name}` (PID: {process.pid})"


def install_dependencies(script_id: int, notify_cb=None) -> tuple[bool, str]:
    """
    Manually scan and install all missing dependencies for a script.
    """
    script = db.get_script_by_id(script_id)
    if not script or script.file_type != "py":
        return False, "❌ السكربت غير موجود أو ليس بايثون."

    if notify_cb:
        notify_cb(f"🔍 جاري فحص المكتبات للملف `{script.file_name}`...")

    try:
        missing = _get_missing_packages(script.file_path)
        if not missing:
            return True, "✅ جميع المكتبات مثبته بالفعل."

        installed_count = 0
        for pkg in missing:
            if notify_cb:
                notify_cb(f"📦 جاري تثبيت `{pkg}`...")
            
            install_cmd = [sys.executable, "-m", "pip", "install", pkg, "--quiet"]
            res = subprocess.run(install_cmd, capture_output=True, text=True, timeout=120)
            
            if res.returncode == 0:
                installed_count += 1
            else:
                return False, f"❌ فشل تثبيت `{pkg}`: {res.stderr[:200]}"

        return True, f"✅ تم تثبيت {installed_count} مكتبة بنجاح."

    except Exception as e:
        logger.error(f"Error installing dependencies for {script_id}: {e}")
        return False, f"❌ خطأ غير متوقع: {str(e)}"


def stop_script(script_id: int) -> tuple[bool, str]:
    """Stop a running script."""
    with _lock:
        info = _processes.get(script_id)
        if not info:
            db.set_script_stopped(script_id)
            return False, "⚠️ السكربت لا يعمل حالياً."

        pid = info["process"].pid
        _close_log(info)
        kill_process_tree(pid)
        del _processes[script_id]

    db.set_script_stopped(script_id)
    logger.info(f"Stopped script {script_id} (PID={pid})")
    return True, "🔴 تم إيقاف السكربت."


def is_running(script_id: int) -> bool:
    with _lock:
        info = _processes.get(script_id)
        if not info:
            return False
        return info["process"].poll() is None


def get_pid(script_id: int) -> Optional[int]:
    with _lock:
        info = _processes.get(script_id)
        return info["process"].pid if info else None


def stop_all():
    """Stop all running scripts (used on shutdown)."""
    with _lock:
        ids = list(_processes.keys())
    for sid in ids:
        stop_script(sid)


def restore_running_scripts(bot_app=None):
    """
    On startup: re-launch all scripts that were running before restart.
    """
    scripts = db.get_running_scripts()
    if not scripts:
        return
    logger.info(f"Restoring {len(scripts)} running scripts...")
    for script, _ in scripts:
        ok, msg = start_script(script)
        logger.info(f"Restore script {script.id}: {msg}")


# ─── Internal ───────────────────────────────────────────────

def _build_command(script: db.Script) -> Optional[list]:
    if script.file_type == "py":
        return [sys.executable, "-u", script.file_path]
    if script.file_type == "js":
        return ["node", script.file_path]
    return None


def cleanup_zombie_processes():
    """Find and kill orphaned child processes (e.g., from crashed scripts) to free RAM."""
    import psutil, os
    logger.info("Scanning for orphaned zombie processes...")
    my_pid = os.getpid()
    tracked_pids = set()
    
    with _lock:
        for sid, info in _processes.items():
            if "process" in info:
                tracked_pids.add(info["process"].pid)
                
    try:
        parent = psutil.Process(my_pid)
        killed_count = 0
        for child in parent.children(recursive=True):
            if child.pid not in tracked_pids:
                logger.warning(f"Killing orphaned process {child.pid} to free RAM.")
                try:
                    child.kill()
                    killed_count += 1
                except psutil.NoSuchProcess:
                    pass
        if killed_count > 0:
            logger.info(f"Killed {killed_count} orphaned processes.")
        else:
            logger.info("No orphaned processes found.")
    except Exception as e:
        logger.error(f"Error cleaning zombie processes: {e}")


def _monitor(script_id: int):
    """Watch a process; handle crash recovery."""
    with _lock:
        info = _processes.get(script_id)
    if not info:
        return

    process    = info["process"]
    script     = info["script"]
    notify_cb  = info.get("notify_cb")

    exit_code = process.wait()  # blocks until process ends
    logger.warning(f"Script {script_id} ({script.file_name}) exited with code {exit_code}")

    with _lock:
        if script_id not in _processes:
            return  # was intentionally stopped
        _close_log(info)
        del _processes[script_id]

    db.set_script_stopped(script_id)

    if notify_cb:
        try:
            notify_cb(f"⚠️ السكربت `{script.file_name}` توقف (exit code: {exit_code}). جاري إعادة التشغيل...")
        except Exception:
            pass

    # Auto-restart with delay
    logger.info(f"Auto-restarting script {script_id} in 5 seconds...")
    time.sleep(5)
    
    ok, msg = start_script(script, notify_cb)
    if notify_cb:
        try:
            notify_cb(msg)
        except Exception:
            pass


def _check_and_install_python_packages(script_path: str) -> tuple[bool, str]:
    """Check for missing Python packages and install them automatically."""
    try:
        missing = _get_missing_packages(script_path)
        if not missing:
            return True, ""
        
        # Install first missing package automatically
        pkg = missing[0]
        install_cmd = [sys.executable, "-m", "pip", "install", pkg, "--quiet"]
        res = subprocess.run(install_cmd, capture_output=True, text=True, timeout=60)
        
        if res.returncode == 0:
            return True, f"✅ تم تثبيت `{pkg}` تلقائياً."
        else:
            return False, f"❌ فشل تثبيت `{pkg}`: {res.stderr[:200]}"
            
    except Exception as e:
        logger.error(f"Auto-install error: {e}")
        return True, ""  # Skip if check fails
    
    return True, ""


def _get_missing_packages(script_path: str) -> list[str]:
    """Extract imports from script and find which ones are not installed."""
    try:
        # 1. Check requirements.txt in the same directory
        req_path = os.path.join(os.path.dirname(script_path), "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                pkgs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                # Simple check for each package
                missing = []
                for p in pkgs:
                    # Strip version specifiers
                    p_clean = re.split(r'[<>=!]', p)[0].strip()
                    try:
                        __import__(p_clean) # Very basic check
                    except ImportError:
                        missing.append(p)
                if missing: return missing

        # 2. Scan script for imports
        with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Regex to find 'import x' or 'from x import ...'
        imports = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
        unique_imports = sorted(list(set(imports)))
        
        missing = []
        for mod in unique_imports:
            pkg = TELEGRAM_MODULES.get(mod.lower(), mod)
            if pkg is None: continue # Core module
            
            try:
                # Try to find the module without executing it
                import importlib.util
                spec = importlib.util.find_spec(mod)
                if spec is None:
                    missing.append(pkg)
            except Exception:
                missing.append(pkg)
                
        return missing
    except Exception as e:
        logger.error(f"Error scanning imports: {e}")
        return []


def _close_log(info: dict):
    lf = info.get("log_file")
    if lf and not lf.closed:
        try:
            lf.close()
        except Exception:
            pass
