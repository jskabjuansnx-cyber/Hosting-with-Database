"""
Script Runner — manages launching, monitoring, and stopping user scripts.
Python-first: 99% of users run .py files.

ضمانات التشغيل:
- السكربت لا يتوقف نهائياً إلا بأمر صريح من المستخدم أو الأدمن
- إعادة تشغيل تلقائية مع backoff ذكي
- إشعار فوري عند أي توقف غير متوقع
- reset تلقائي للعداد لو السكربت شغل فترة كافية
"""
import os
import sys
import ast
import logging
import subprocess
import threading
import re
import time
from datetime import datetime
from typing import Optional, Callable

import psutil

import database as db
from config import MAX_PROCESSES, TELEGRAM_MODULES, SCRIPTS_DIR
from utils.helpers import get_log_path, kill_process_tree

logger = logging.getLogger(__name__)

# ─── In-memory process registry ─────────────────────────────
_processes: dict[int, dict] = {}
_lock = threading.Lock()

# إعدادات إعادة التشغيل
MAX_RESTART_ATTEMPTS  = 10          # حد أعلى — بعده يوقف ويبلغ
RESTART_RESET_SECONDS = 120         # لو شغل دقيقتين بدون crash → reset العداد
RESTART_BACKOFF       = [5, 10, 20, 30, 60]  # تأخير متصاعد بين المحاولات (ثواني)

_restart_counts:  dict[int, int]   = {}
_start_times:     dict[int, float] = {}
# notify_cb الدائم — يُحفظ حتى بعد restart عشان المستخدم يفضل يتبلغ
_notify_registry: dict[int, Callable] = {}
# علامة الإيقاف المتعمد — يمنع إعادة التشغيل
_intentional_stop: set[int] = set()


# ─── Path Resolution ─────────────────────────────────────────

def resolve_script_path(script: db.Script) -> str:
    """
    يحل مسار الملف بشكل ذكي.
    1. المسار المخزون موجود → يستخدمه
    2. يبني المسار من SCRIPTS_DIR/owner_id/file_name
    """
    if script.file_path and os.path.exists(script.file_path):
        return script.file_path

    rebuilt = os.path.join(SCRIPTS_DIR, str(script.owner_id), script.file_name)
    if os.path.exists(rebuilt):
        _update_script_path(script.id, rebuilt)
        logger.info(f"Resolved path for script {script.id}: {rebuilt}")
        return rebuilt

    return script.file_path


def _update_script_path(script_id: int, new_path: str):
    try:
        with db.get_session() as s:
            sc = s.get(db.Script, script_id)
            if sc:
                sc.file_path = new_path
    except Exception as e:
        logger.error(f"Failed to update script path {script_id}: {e}")


# ─── Python Syntax Check ─────────────────────────────────────

def check_python_syntax(file_path: str) -> tuple[bool, str]:
    """
    يفحص syntax الكود قبل التشغيل.
    Returns (is_valid, error_message)
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        ast.parse(source, filename=os.path.basename(file_path))
        return True, ""
    except SyntaxError as e:
        return False, (
            f"❌ خطأ في الكود (Syntax Error)\n\n"
            f"السطر: {e.lineno}\n"
            f"المشكلة: `{e.msg}`\n"
            f"الكود: `{(e.text or '').strip()}`\n\n"
            "صحح الخطأ وأعد رفع الملف."
        )
    except Exception:
        return True, ""


# ─── Public API ─────────────────────────────────────────────

def start_script(script: db.Script, notify_cb: Callable = None) -> tuple[bool, str]:
    """
    يشغل السكربت. Returns (success, message).
    notify_cb: callback لإرسال رسائل للمستخدم — يُحفظ دائماً حتى بعد restart.
    """
    with _lock:
        if len(_processes) >= MAX_PROCESSES:
            return False, f"❌ تم الوصول للحد الأقصى من العمليات ({MAX_PROCESSES})."
        if script.id in _processes:
            return False, "⚠️ السكربت يعمل بالفعل."

    # إزالة من قائمة الإيقاف المتعمد عند التشغيل الجديد
    _intentional_stop.discard(script.id)

    # حفظ notify_cb دائماً (حتى لو None لا نمسح القديم)
    if notify_cb is not None:
        _notify_registry[script.id] = notify_cb

    resolved_path = resolve_script_path(script)

    if not os.path.exists(resolved_path):
        db.set_script_stopped(script.id)
        return False, (
            f"❌ الملف غير موجود: `{script.file_name}`\n\n"
            "الأسباب المحتملة:\n"
            "• تم حذف الملف من السيرفر\n"
            "• تغيير مسار التخزين بعد إعادة النشر\n\n"
            "الحل: احذف السكربت وأعد رفعه."
        )

    script.file_path = resolved_path

    # ─── Python-specific checks ──────────────────────────────
    if script.file_type == "py":
        valid, syntax_err = check_python_syntax(resolved_path)
        if not valid:
            db.set_script_stopped(script.id)
            return False, syntax_err

        ok, install_msg = _check_and_install_python_packages(resolved_path)
        if not ok:
            return False, install_msg

    log_path = get_log_path(script.owner_id, script.file_name)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8", errors="ignore")
    except Exception as e:
        return False, f"❌ فشل فتح ملف السجل: {e}"

    cmd = _build_command(script)
    if not cmd:
        log_file.close()
        return False, f"❌ نوع الملف غير مدعوم: `{script.file_type}`"

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"]      = "utf-8"
        env["PYTHONUTF8"]            = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        process = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(script.file_path),
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError as e:
        log_file.close()
        return False, f"❌ Python غير موجود على السيرفر.\nالتفاصيل: {e}"
    except PermissionError as e:
        log_file.close()
        return False, f"❌ لا توجد صلاحية لتشغيل الملف: {e}"
    except Exception as e:
        log_file.close()
        return False, f"❌ خطأ في تشغيل السكربت: {e}"

    with _lock:
        _processes[script.id] = {
            "process":    process,
            "log_file":   log_file,
            "start_time": datetime.utcnow(),
            "script":     script,
        }
        _start_times[script.id] = time.monotonic()

    db.set_script_running(script.id, process.pid)
    logger.info(f"Started script {script.id} ({script.file_name}) PID={process.pid}")

    threading.Thread(
        target=_monitor,
        args=(script.id,),
        daemon=True,
        name=f"monitor-{script.id}",
    ).start()

    return True, f"✅ تم تشغيل `{script.file_name}` (PID: {process.pid})"


def stop_script(script_id: int, intentional: bool = True) -> tuple[bool, str]:
    """
    يوقف السكربت.
    intentional=True → لا يُعاد تشغيله تلقائياً.
    intentional=False → يُعاد تشغيله (للاستخدام الداخلي فقط).
    """
    if intentional:
        _intentional_stop.add(script_id)

    with _lock:
        info = _processes.get(script_id)
        if not info:
            db.set_script_stopped(script_id)
            return False, "⚠️ السكربت لا يعمل حالياً."

        pid = info["process"].pid
        _close_log(info)
        kill_process_tree(pid)
        del _processes[script_id]

    if intentional:
        _restart_counts.pop(script_id, None)
        _start_times.pop(script_id, None)
        # لا نمسح notify_registry عشان المستخدم يفضل يتبلغ لو حصل شيء

    db.set_script_stopped(script_id)
    logger.info(f"Stopped script {script_id} (PID={pid}, intentional={intentional})")
    return True, "🔴 تم إيقاف السكربت."


def restart_script(script_id: int) -> tuple[bool, str]:
    """إعادة تشغيل نظيفة — يوقف ويشغل من أول."""
    script = db.get_script_by_id(script_id)
    if not script:
        return False, "❌ السكربت غير موجود."

    # إيقاف غير متعمد (عشان يسمح بإعادة التشغيل)
    stop_script(script_id, intentional=False)
    _intentional_stop.discard(script_id)
    _restart_counts.pop(script_id, None)  # reset العداد عند restart يدوي

    time.sleep(1)
    return start_script(script, _notify_registry.get(script_id))


def is_running(script_id: int) -> bool:
    with _lock:
        info = _processes.get(script_id)
        if not info:
            return False
        return info["process"].poll() is None


def get_uptime(script_id: int) -> Optional[str]:
    """مدة تشغيل السكربت كنص مقروء."""
    with _lock:
        info = _processes.get(script_id)
        if not info:
            return None
        delta = datetime.utcnow() - info["start_time"]

    total = int(delta.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d:
        return f"{d}ي {h}س {m}د"
    if h:
        return f"{h}س {m}د {s}ث"
    return f"{m}د {s}ث"


def get_resource_usage(script_id: int) -> Optional[dict]:
    """يرجع استخدام CPU والذاكرة للسكربت."""
    with _lock:
        info = _processes.get(script_id)
        if not info:
            return None
        pid = info["process"].pid

    try:
        proc = psutil.Process(pid)
        cpu  = proc.cpu_percent(interval=0.2)
        mem  = proc.memory_info().rss / (1024 * 1024)  # MB
        return {"cpu": round(cpu, 1), "mem": round(mem, 1)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def get_pid(script_id: int) -> Optional[int]:
    with _lock:
        info = _processes.get(script_id)
        return info["process"].pid if info else None


def stop_all():
    with _lock:
        ids = list(_processes.keys())
    for sid in ids:
        stop_script(sid, intentional=True)


def restore_running_scripts(bot_app=None):
    """إعادة تشغيل السكربتات بعد restart البوت."""
    scripts = db.get_running_scripts()
    if not scripts:
        return
    logger.info(f"Restoring {len(scripts)} running scripts...")
    for script, _ in scripts:
        resolved = resolve_script_path(script)
        if not os.path.exists(resolved):
            logger.warning(f"Script {script.id} ({script.file_name}) not found — marking stopped.")
            db.set_script_stopped(script.id)
            continue
        script.file_path = resolved

        # نبني notify_cb تلقائي لو عندنا bot_app
        if bot_app and script.id not in _notify_registry:
            owner_id = script.owner_id
            def _make_cb(app, uid):
                def cb(msg):
                    app.create_task(app.bot.send_message(uid, msg))
                return cb
            _notify_registry[script.id] = _make_cb(bot_app, owner_id)

        ok, msg = start_script(script)
        logger.info(f"Restore script {script.id}: {msg}")


def get_script_health(script_id: int) -> dict:
    """تقرير صحة شامل للسكربت."""
    script = db.get_script_by_id(script_id)
    if not script:
        return {"status": "not_found"}

    resolved        = resolve_script_path(script)
    file_exists     = os.path.exists(resolved)
    is_proc_running = is_running(script_id)
    db_status       = db.get_script_status(script_id)
    restart_count   = _restart_counts.get(script_id, 0)
    uptime          = get_uptime(script_id)
    resources       = get_resource_usage(script_id) if is_proc_running else None

    syntax_ok, syntax_err = True, ""
    if file_exists and script.file_type == "py":
        syntax_ok, syntax_err = check_python_syntax(resolved)

    missing_pkgs = []
    if file_exists and script.file_type == "py":
        try:
            missing_pkgs = _get_missing_packages(resolved)
        except Exception:
            pass

    issues = []
    if not file_exists:
        issues.append("الملف غير موجود على السيرفر")
    if not syntax_ok:
        issues.append(f"خطأ في الكود: {syntax_err[:80]}")
    if missing_pkgs:
        issues.append(f"مكتبات ناقصة: {', '.join(missing_pkgs[:3])}")
    if db_status and db_status.is_running and not is_proc_running:
        issues.append("قاعدة البيانات تقول شغال لكن العملية متوقفة")
    if restart_count >= MAX_RESTART_ATTEMPTS:
        issues.append(f"توقف إعادة التشغيل بعد {restart_count} محاولة")

    return {
        "status":        "running" if is_proc_running else "stopped",
        "file_exists":   file_exists,
        "file_path":     resolved,
        "restart_count": restart_count,
        "uptime":        uptime,
        "resources":     resources,
        "syntax_ok":     syntax_ok,
        "missing_pkgs":  missing_pkgs,
        "issues":        issues,
        "file_type":     script.file_type,
        "auto_restart":  script_id not in _intentional_stop,
    }


def install_dependencies(script_id: int, notify_cb=None) -> tuple[bool, str]:
    """تثبيت يدوي لكل المكتبات الناقصة مع تقرير تفصيلي."""
    script = db.get_script_by_id(script_id)
    if not script or script.file_type != "py":
        return False, "❌ السكربت غير موجود أو ليس Python."

    resolved = resolve_script_path(script)
    if not os.path.exists(resolved):
        return False, f"❌ الملف غير موجود على السيرفر: `{script.file_name}`"

    if notify_cb:
        notify_cb(f"🔍 جاري فحص المكتبات للملف `{script.file_name}`...")

    try:
        missing = _get_missing_packages(resolved)
        if not missing:
            return True, "✅ جميع المكتبات مثبتة بالفعل."

        results = []
        for pkg in missing:
            if notify_cb:
                notify_cb(f"📦 جاري تثبيت `{pkg}`...")

            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"],
                capture_output=True, text=True, timeout=120
            )
            if res.returncode == 0:
                results.append(f"✅ {pkg}")
            else:
                results.append(f"❌ {pkg}: {res.stderr.strip()[:100]}")

        success = all(r.startswith("✅") for r in results)
        report  = "\n".join(results)
        return (True, f"✅ تم تثبيت {len(missing)} مكتبة:\n{report}") if success \
               else (False, f"⚠️ نتائج التثبيت:\n{report}")

    except Exception as e:
        logger.error(f"Error installing dependencies for {script_id}: {e}")
        return False, f"❌ خطأ غير متوقع: {str(e)}"


# ─── Internal ───────────────────────────────────────────────

def _build_command(script: db.Script) -> Optional[list]:
    if script.file_type == "py":
        return [sys.executable, "-u", script.file_path]
    if script.file_type == "js":
        return ["node", script.file_path]
    return None


def cleanup_zombie_processes():
    """يقتل العمليات اليتيمة لتحرير الذاكرة."""
    logger.info("Scanning for orphaned zombie processes...")
    my_pid = os.getpid()
    tracked_pids = set()

    with _lock:
        for info in _processes.values():
            if "process" in info:
                tracked_pids.add(info["process"].pid)

    try:
        parent = psutil.Process(my_pid)
        killed = 0
        for child in parent.children(recursive=True):
            if child.pid not in tracked_pids:
                try:
                    child.kill()
                    killed += 1
                except psutil.NoSuchProcess:
                    pass
        logger.info(f"Killed {killed} orphaned processes." if killed else "No orphaned processes.")
    except Exception as e:
        logger.error(f"Error cleaning zombie processes: {e}")


def _notify(script_id: int, msg: str):
    """يرسل إشعار للمستخدم باستخدام الـ callback المحفوظ."""
    cb = _notify_registry.get(script_id)
    if cb:
        try:
            cb(msg)
        except Exception as e:
            logger.warning(f"notify_cb failed for script {script_id}: {e}")


def _monitor(script_id: int):
    """
    يراقب العملية ويعيد تشغيلها تلقائياً ما لم يكن الإيقاف متعمداً.
    يضمن أن السكربت لا يتوقف نهائياً إلا بأمر صريح.
    """
    with _lock:
        info = _processes.get(script_id)
    if not info:
        return

    process = info["process"]
    script  = info["script"]

    exit_code = process.wait()
    logger.warning(f"Script {script_id} ({script.file_name}) exited with code {exit_code}")

    with _lock:
        if script_id not in _processes:
            return  # تم الإيقاف يدوياً من stop_script
        _close_log(info)
        del _processes[script_id]

    db.set_script_stopped(script_id)

    # لو الإيقاف كان متعمداً → لا نعيد التشغيل
    if script_id in _intentional_stop:
        logger.info(f"Script {script_id} was intentionally stopped — no restart.")
        return

    # reset العداد لو السكربت شغل فترة كافية
    start_t = _start_times.pop(script_id, None)
    if start_t and (time.monotonic() - start_t) >= RESTART_RESET_SECONDS:
        _restart_counts[script_id] = 0
        logger.info(f"Script {script_id} ran >{RESTART_RESET_SECONDS}s — reset restart counter.")

    attempts = _restart_counts.get(script_id, 0) + 1
    _restart_counts[script_id] = attempts

    # تحقق من وجود الملف
    resolved = resolve_script_path(script)
    if not os.path.exists(resolved):
        _notify(script_id,
            f"❌ السكربت `{script.file_name}` توقف.\n"
            "الملف غير موجود على السيرفر.\n"
            "الحل: احذف السكربت وأعد رفعه."
        )
        return

    # تحقق من الـ syntax قبل إعادة التشغيل
    if script.file_type == "py":
        valid, syntax_err = check_python_syntax(resolved)
        if not valid:
            _notify(script_id,
                f"❌ السكربت `{script.file_name}` توقف بسبب خطأ في الكود.\n"
                f"{syntax_err}\n\n"
                "صحح الخطأ وأعد رفع الملف."
            )
            return

    # حد إعادة المحاولة
    if attempts > MAX_RESTART_ATTEMPTS:
        _notify(script_id,
            f"🛑 السكربت `{script.file_name}` توقف {attempts} مرة متتالية.\n"
            "تم إيقاف إعادة التشغيل التلقائي.\n\n"
            "افتح السجل لمعرفة سبب التوقف المتكرر.\n"
            "يمكنك إعادة تشغيله يدوياً من قائمة ملفاتك."
        )
        logger.error(f"Script {script_id} exceeded max restart attempts ({MAX_RESTART_ATTEMPTS})")
        return

    # تأخير متصاعد بين المحاولات
    delay = RESTART_BACKOFF[min(attempts - 1, len(RESTART_BACKOFF) - 1)]

    _notify(script_id,
        f"⚠️ السكربت `{script.file_name}` توقف (exit: {exit_code}).\n"
        f"إعادة التشغيل خلال {delay} ثانية... (محاولة {attempts}/{MAX_RESTART_ATTEMPTS})"
    )

    logger.info(f"Auto-restarting script {script_id} in {delay}s (attempt {attempts})...")
    time.sleep(delay)

    # تحقق مرة أخرى قبل التشغيل (ممكن المستخدم أوقفه في فترة الانتظار)
    if script_id in _intentional_stop:
        logger.info(f"Script {script_id} stopped during backoff — skipping restart.")
        return

    script.file_path = resolved
    ok, msg = start_script(script)  # notify_cb محفوظ في _notify_registry
    if not ok:
        _notify(script_id, f"❌ فشل إعادة تشغيل `{script.file_name}`:\n{msg}")


def _check_and_install_python_packages(script_path: str) -> tuple[bool, str]:
    """تثبيت تلقائي لكل المكتبات الناقصة."""
    try:
        missing = _get_missing_packages(script_path)
        if not missing:
            return True, ""

        for pkg in missing:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"],
                capture_output=True, text=True, timeout=120
            )
            if res.returncode != 0:
                return False, (
                    f"❌ فشل تثبيت المكتبة `{pkg}`\n"
                    f"السبب: `{res.stderr.strip()[:200]}`\n\n"
                    "جرب تثبيتها يدوياً من زر 'تثبيت المكتبات'."
                )

        logger.info(f"Auto-installed {len(missing)} packages: {missing}")
        return True, ""

    except Exception as e:
        logger.error(f"Auto-install error: {e}")
        return True, ""


def _get_missing_packages(script_path: str) -> list[str]:
    """يستخرج الـ imports ويجد المكتبات الغير مثبتة."""
    try:
        # 1. requirements.txt
        req_path = os.path.join(os.path.dirname(script_path), "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                pkgs = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            missing = []
            for p in pkgs:
                p_clean = re.split(r'[<>=!;\[]', p)[0].strip()
                if p_clean and not _is_installed(p_clean):
                    missing.append(p)
            if missing:
                return missing

        # 2. فحص الـ imports بـ AST
        with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split(".")[0])
        except SyntaxError:
            raw = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', source, re.MULTILINE)
            imports = set(raw)

        missing = []
        for mod in sorted(imports):
            mod_lower = mod.lower()
            if TELEGRAM_MODULES.get(mod_lower) is None and mod_lower in TELEGRAM_MODULES:
                continue
            pkg = TELEGRAM_MODULES.get(mod_lower, mod)
            if not _is_installed(mod):
                missing.append(pkg)

        return missing

    except Exception as e:
        logger.error(f"Error scanning imports: {e}")
        return []


def _is_installed(module_name: str) -> bool:
    """تحقق سريع من تثبيت مكتبة."""
    import importlib.util
    try:
        name = module_name.replace("-", "_").split("[")[0].split(".")[0]
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _close_log(info: dict):
    lf = info.get("log_file")
    if lf and not lf.closed:
        try:
            lf.flush()
            lf.close()
        except Exception:
            pass
