"""
Database layer using SQLAlchemy.
All tables are defined here and accessed via session context managers.
"""
import logging
from contextlib import contextmanager
from datetime import datetime
import os

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean,
    DateTime, Text, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ─── Engine ─────────────────────────────────────────────────
_connect_args = {}
_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    _kwargs = {"poolclass": StaticPool}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
    **_kwargs
)

# Enable WAL mode for SQLite (better concurrency)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ─── Models ─────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)          # Telegram user_id
    username      = Column(String(64), nullable=True)
    full_name     = Column(String(128), nullable=True)
    is_admin      = Column(Boolean, default=False)
    is_banned     = Column(Boolean, default=False)
    ban_reason    = Column(String(256), nullable=True)
    subscription_expiry = Column(DateTime, nullable=True)
    has_uploaded_free   = Column(Boolean, default=False)   # رفع ملف مجاني قبل كده
    free_uploads_used   = Column(Integer, default=0)       # عدد الملفات المرفوعة تاريخياً
    joined_at     = Column(DateTime, default=datetime.utcnow)


class Script(Base):
    __tablename__ = "scripts"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    owner_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_name     = Column(String(256), nullable=False)
    file_type     = Column(String(8),   nullable=False)        # py | js
    file_path     = Column(String(512), nullable=False)
    uploaded_at   = Column(DateTime, default=datetime.utcnow)


class ScriptStatus(Base):
    __tablename__ = "scripts_status"
    script_id     = Column(Integer, ForeignKey("scripts.id"), primary_key=True)
    is_running    = Column(Boolean, default=False)
    pid           = Column(Integer, nullable=True)
    started_at    = Column(DateTime, nullable=True)
    stopped_at    = Column(DateTime, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    script_id     = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    status        = Column(String(16), default="pending")      # pending|approved|rejected
    reviewed_by   = Column(Integer, nullable=True)
    reviewed_at   = Column(DateTime, nullable=True)
    note          = Column(String(256), nullable=True)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    key           = Column(String(64), primary_key=True)
    enabled       = Column(Boolean, default=True)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Config(Base):
    __tablename__ = "config"
    key           = Column(String(64), primary_key=True)
    value         = Column(String(256), nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LogMeta(Base):
    __tablename__ = "logs_meta"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    script_id     = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    log_path      = Column(String(512), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)


class EmojiConfig(Base):
    """جدول لتخزين Custom Emoji IDs القابلة للتعديل من لوحة التحكم."""
    __tablename__ = "emoji_config"
    key           = Column(String(64), primary_key=True)   # اسم الإيموجي مثل WAVE, CROWN2
    emoji_id      = Column(String(64), nullable=False)     # الـ custom emoji ID
    emoji_char    = Column(String(8),  nullable=False)     # الحرف المقابل مثل 👋
    description   = Column(String(128), nullable=True)     # وصف للأدمن


# ─── Session helper ─────────────────────────────────────────

@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Init ───────────────────────────────────────────────────

DEFAULT_FLAGS = [
    "upload_enabled",
    "run_enabled",
    "approval_required",
    "bot_enabled",
    "bot_locked",
]

DEFAULT_CONFIG = {
    "free_file_limit":  "3",
    "paid_file_limit":  "15",
    "max_processes":    "50",
    "your_username":    "@P_X_24",
    "update_channel":   "https://t.me/Raven_xx24",
}

# الإيموجيات القابلة للتعديل من لوحة التحكم
# key: (emoji_char, emoji_id, description)
DEFAULT_EMOJIS = {
    # ─── رسالة الترحيب /start ──────────────────────────────
    "WAVE":         ("👋", "5353027129250422669", "تحية الترحيب في /start"),
    "MASK":         ("🎭", "5359441070201513074", "إيموجي الدور في /start"),
    "FOLDER2":      ("📁", "5433653135799228968", "حد الملفات في /start"),
    "BRAIN":        ("🧠", "5226639745106330551", "وصف البوت في /start"),
    # ─── أدوار المستخدمين ──────────────────────────────────
    "CROWN2":       ("👑", "5364042960155472936", "دور الأدمن"),
    "FREE_USER":    ("👤", "5848155425899287189", "دور المجاني"),
    "PAID_USER":    ("💎", "6251075258648891976", "دور المشترك"),
    # ─── سرعة البوت ────────────────────────────────────────
    "LIGHTNING2":   ("⚡", "5363845026587634369", "سرعة البوت"),
    "TIMER":        ("⏱", "5382194935057372936", "وقت الاستجابة"),
    "CLOCK":        ("⏰", "5413704112220949842", "وقت التشغيل"),
    "MASK2":        ("🎭", "5359441070201513074", "الدور في الإحصائيات"),
    # ─── الإحصائيات ────────────────────────────────────────
    "UP_CHART":     ("📊", "5028746137645876535", "الإحصائيات"),
    "ID_BADGE":     ("🆔", "5965340962870793287", "المعرف"),
    "GREEN_DOT":    ("🟢", "5364150781014470870", "مؤشر التشغيل"),
    # ─── الملفات ───────────────────────────────────────────
    "FOLDER3":      ("📂", "5332586662629227075", "قائمة الملفات"),
    "UPLOAD3":      ("📤", "5363793701728450630", "رفع ملف"),
    "NOTE":         ("📝", "5846014758364386016", "السجل"),
    # ─── القائمة الرئيسية (أزرار) ──────────────────────────
    "BTN_UPLOAD":   ("📤", "5433614747381538714", "زر رفع ملف"),
    "BTN_FILES":    ("🗂", "5798700621242568649", "زر ملفاتي"),
    "BTN_SPEED":    ("⚡", "5967301267549068409", "زر سرعة البوت"),
    "BTN_STATS":    ("📈", "5028746137645876535", "زر إحصائياتي"),
    "BTN_CONTACT":  ("📞", "5386335214811233128", "زر التواصل مع المالك"),
    "BTN_ADMIN":    ("👑", "5965019600532806099", "زر لوحة الأدمن"),
    "BTN_BACK":     ("🔙", "5253997076169115797", "زر رجوع"),
    # ─── رسائل النظام ──────────────────────────────────────
    "BANNED":       ("🚫", "5465665476971471368", "رسالة المحظور"),
    "LOCKED":       ("🔒", "5384558459855324597", "رسالة البوت مغلق"),
    "SUCCESS":      ("✅", "5967518416800585747", "رسالة نجاح"),
    "ERROR":        ("❌", "5465665476971471368", "رسالة خطأ"),
    "WARNING":      ("⚠️", "5467666648801048327", "رسالة تحذير"),
    "SHIELD":       ("🛡", "5467666648801048327", "رسالة أمان"),
    "NEW_USER":     ("👤", "5846115273484014293", "إشعار مستخدم جديد"),
    # ─── أزرار السكربت ─────────────────────────────────────
    "BTN_STOP":     ("⏹", "6084515769780013003",  "زر إيقاف السكربت"),
    "BTN_RUN":      ("▶️", "5363845026587634369", "زر تشغيل السكربت"),
    "BTN_RESTART":  ("🔄", "5226702984204797593", "زر إعادة تشغيل"),
    "BTN_INSTALL":  ("📦", "5798700621242568649", "زر تثبيت المكتبات"),
    "BTN_LOG":      ("📋", "5846014758364386016", "زر السجل"),
    "BTN_UPDATE":   ("🔄", "5226702984204797593", "زر تحديث الملف"),
    "BTN_DIAGNOSE": ("🔍", "5798700621242568649", "زر تشخيص"),
    "BTN_DELETE":   ("🗑",  "5445267414562389170", "زر حذف"),
    "BTN_AUTO_ON":  ("🔁", "5226702984204797593", "زر تلقائي مفعل"),
    "BTN_APPROVE":  ("✅", "5967518416800585747", "زر موافقة"),
    "BTN_REJECT":   ("❌", "5465665476971471368", "زر رفض"),
    "BTN_VIEWCODE": ("👁", "5798700621242568649", "زر عرض الكود"),
    "BTN_CONTACT_OPEN": ("💬", "5386335214811233128", "زر فتح المحادثة"),
    # ─── حالات السكربت ─────────────────────────────────────
    "STATUS_ON":    ("🟢", "5364150781014470870", "حالة يعمل"),
    "STATUS_OFF":   ("🔴", "5798700621242568649", "حالة متوقف"),
    "STATUS_WAIT":  ("⏳", "5382194935057372936", "حالة انتظار"),
    "STATUS_STOP":  ("🛑", "6084515769780013003", "حالة توقف نهائي"),
    # ─── رسائل الملفات ─────────────────────────────────────
    "FILE_ICON":    ("📂", "5332586662629227075", "أيقونة الملف"),
    "FILE_TYPE":    ("🔧", "5339139919434498721", "نوع الملف"),
    "FILE_DATE":    ("📅", "5413704112220949842", "تاريخ الرفع"),
    "FILE_CPU":     ("⚙️", "5339139919434498721", "مؤشر CPU"),
    "FILE_RESTART": ("🔁", "5226702984204797593", "عداد إعادة التشغيل"),
    "FILE_APPROVE": ("📋", "5846014758364386016", "طلب موافقة"),
    "FILE_USER":    ("👤", "5846115273484014293", "مستخدم في الموافقة"),
    "FILE_DOC":     ("📄", "5846014758364386016", "اسم الملف في الموافقة"),
    # ─── مزايا جديدة ───────────────────────────────────────
    "BTN_STATUS":   ("📡", "5798700621242568649", "زر حالة السكربتات"),
    "BTN_HELP":     ("❓", "5798700621242568649", "زر المساعدة"),
    "HELP_ICON":    ("📖", "5798700621242568649", "أيقونة المساعدة"),
    "SCRIPT_ON":    ("🟢", "5364150781014470870", "سكربت شغال في القائمة"),
    "SCRIPT_OFF":   ("⚫", "5798700621242568649", "سكربت واقف في القائمة"),
    "UPTIME_ICON":  ("⏱", "5382194935057372936", "مدة التشغيل"),
    "RESTART_CNT":  ("🔁", "5226702984204797593", "عدد إعادة التشغيل"),
    "SUB_EXPIRY":   ("📅", "5413704112220949842", "تاريخ انتهاء الاشتراك"),
    "NOTIFY_ICON":  ("🔔", "5798700621242568649", "إشعار توقف السكربت"),
    "PYTHON_ICON":  ("🐍", "5798700621242568649", "أيقونة Python"),
    "JS_ICON":      ("📜", "5798700621242568649", "أيقونة JavaScript"),
}


def init_db(owner_id: int):
    Base.metadata.create_all(engine)

    # Run migrations for existing databases
    _run_migrations()

    with get_session() as s:
        # Ensure owner exists
        owner = s.get(User, owner_id)
        if not owner:
            owner = User(id=owner_id, is_admin=True)
            s.add(owner)

        # Default feature flags
        for flag in DEFAULT_FLAGS:
            if not s.get(FeatureFlag, flag):
                s.add(FeatureFlag(key=flag, enabled=True))

        # Default config
        for k, v in DEFAULT_CONFIG.items():
            if not s.get(Config, k):
                s.add(Config(key=k, value=v))

        # Default emoji config
        for key, (char, eid, desc) in DEFAULT_EMOJIS.items():
            if not s.get(EmojiConfig, key):
                s.add(EmojiConfig(key=key, emoji_id=eid, emoji_char=char, description=desc))

    logger.info("Database initialised.")


def _run_migrations():
    """Add missing columns to existing databases without losing data."""
    import sqlite3 as _sqlite3
    if not DATABASE_URL.startswith("sqlite"):
        return
    
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    
    migrations = [
        ("users", "has_uploaded_free",  "BOOLEAN DEFAULT 0"),
        ("users", "ban_reason",         "TEXT"),
        ("users", "subscription_expiry","DATETIME"),
        ("users", "free_uploads_used",  "INTEGER DEFAULT 0"),
    ]
    
    try:
        conn = _sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in c.fetchall()}
        
        for table, col, col_type in migrations:
            if col not in existing_cols:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    logger.info(f"Migration: added column {col} to {table}")
                except Exception as e:
                    logger.warning(f"Migration skip {col}: {e}")
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Migration error: {e}")


# ─── Helpers ────────────────────────────────────────────────

def get_flag(key: str) -> bool:
    with get_session() as s:
        row = s.get(FeatureFlag, key)
        return row.enabled if row else True


def set_flag(key: str, value: bool):
    with get_session() as s:
        row = s.get(FeatureFlag, key)
        if row:
            row.enabled = value
        else:
            s.add(FeatureFlag(key=key, enabled=value))


def get_config(key: str, default: str = "") -> str:
    with get_session() as s:
        row = s.get(Config, key)
        return row.value if row else default


def set_config(key: str, value: str):
    with get_session() as s:
        row = s.get(Config, key)
        if row:
            row.value = value
        else:
            s.add(Config(key=key, value=value))


def reset_user_upload_status(user_id: int):
    """Reset user's free upload status when they subscribe."""
    with get_session() as s:
        user = s.get(User, user_id)
        if user:
            user.has_uploaded_free = False


def get_user(user_id: int) -> User | None:
    with get_session() as s:
        return s.get(User, user_id)


def upsert_user(user_id: int, username: str = None, full_name: str = None):
    with get_session() as s:
        user = s.get(User, user_id)
        if not user:
            user = User(id=user_id, username=username, full_name=full_name)
            s.add(user)
        else:
            if username:  user.username  = username
            if full_name: user.full_name = full_name


def is_admin(user_id: int) -> bool:
    with get_session() as s:
        user = s.get(User, user_id)
        return bool(user and user.is_admin)


def is_banned(user_id: int) -> bool:
    with get_session() as s:
        user = s.get(User, user_id)
        return bool(user and user.is_banned)


def is_subscribed(user_id: int) -> bool:
    with get_session() as s:
        user = s.get(User, user_id)
        if not user or not user.subscription_expiry:
            return False
        return user.subscription_expiry > datetime.utcnow()


def get_user_scripts(user_id: int) -> list[Script]:
    with get_session() as s:
        scripts = s.query(Script).filter_by(owner_id=user_id).all()
        s.expunge_all()
        return scripts


def get_script_by_id(script_id: int) -> Script | None:
    with get_session() as s:
        script = s.get(Script, script_id)
        if script:
            s.expunge(script)
        return script


def add_script(owner_id: int, file_name: str, file_type: str, file_path: str) -> Script:
    with get_session() as s:
        script = Script(
            owner_id=owner_id,
            file_name=file_name,
            file_type=file_type,
            file_path=file_path,
        )
        s.add(script)
        s.flush()
        s.add(ScriptStatus(script_id=script.id))
        s.expunge(script)
        return script


def delete_script(script_id: int):
    with get_session() as s:
        s.query(LogMeta).filter_by(script_id=script_id).delete()
        s.query(Approval).filter_by(script_id=script_id).delete()
        s.query(ScriptStatus).filter_by(script_id=script_id).delete()
        script = s.get(Script, script_id)
        if script:
            s.delete(script)


def get_script_status(script_id: int) -> ScriptStatus | None:
    with get_session() as s:
        st = s.get(ScriptStatus, script_id)
        if st:
            s.expunge(st)
        return st


def set_script_running(script_id: int, pid: int):
    with get_session() as s:
        st = s.get(ScriptStatus, script_id)
        if st:
            st.is_running = True
            st.pid        = pid
            st.started_at = datetime.utcnow()
            st.stopped_at = None


def set_script_stopped(script_id: int):
    with get_session() as s:
        st = s.get(ScriptStatus, script_id)
        if st:
            st.is_running = False
            st.pid        = None
            st.stopped_at = datetime.utcnow()


def get_running_scripts() -> list[tuple[Script, ScriptStatus]]:
    """Return all scripts marked as running in DB (used on restart)."""
    with get_session() as s:
        rows = (
            s.query(Script, ScriptStatus)
            .join(ScriptStatus, Script.id == ScriptStatus.script_id)
            .filter(ScriptStatus.is_running == True)
            .all()
        )
        result = []
        for sc, st in rows:
            s.expunge(sc)
            s.expunge(st)
            result.append((sc, st))
        return result


def add_approval(script_id: int) -> Approval:
    with get_session() as s:
        ap = Approval(script_id=script_id, status="pending")
        s.add(ap)
        s.flush()
        s.expunge(ap)
        return ap


def update_approval(approval_id: int, status: str, reviewed_by: int, note: str = None):
    with get_session() as s:
        ap = s.get(Approval, approval_id)
        if ap:
            ap.status      = status
            ap.reviewed_by = reviewed_by
            ap.reviewed_at = datetime.utcnow()
            ap.note        = note


def get_pending_approvals() -> list[tuple[Approval, Script]]:
    with get_session() as s:
        rows = (
            s.query(Approval, Script)
            .join(Script, Approval.script_id == Script.id)
            .filter(Approval.status == "pending")
            .all()
        )
        result = []
        for ap, sc in rows:
            s.expunge(ap)
            s.expunge(sc)
            result.append((ap, sc))
        return result


# ─── Emoji Config Helpers ────────────────────────────────────

def get_emoji(key: str) -> tuple[str, str]:
    """Returns (emoji_char, emoji_id) for a given key. Falls back to DEFAULT_EMOJIS."""
    with get_session() as s:
        row = s.get(EmojiConfig, key)
        if row:
            return (row.emoji_char, row.emoji_id)
    # fallback to hardcoded defaults
    default = DEFAULT_EMOJIS.get(key)
    if default:
        return (default[0], default[1])
    return ("❓", "")


def set_emoji(key: str, emoji_id: str, emoji_char: str = None):
    """Update emoji_id (and optionally emoji_char) for a key."""
    with get_session() as s:
        row = s.get(EmojiConfig, key)
        if row:
            row.emoji_id = emoji_id
            if emoji_char:
                row.emoji_char = emoji_char
        else:
            char = emoji_char or DEFAULT_EMOJIS.get(key, ("❓",))[0]
            desc = DEFAULT_EMOJIS.get(key, ("", "", ""))[2]
            s.add(EmojiConfig(key=key, emoji_id=emoji_id, emoji_char=char, description=desc))


def get_all_emojis() -> list[EmojiConfig]:
    """Return all emoji config rows."""
    with get_session() as s:
        rows = s.query(EmojiConfig).order_by(EmojiConfig.key).all()
        for r in rows:
            s.expunge(r)
        return rows


def get_free_upload_count(user_id: int) -> int:
    """عدد الملفات اللي رفعها المستخدم المجاني تاريخياً (مش الموجودة حالياً)."""
    with get_session() as s:
        user = s.get(User, user_id)
        return user.free_uploads_used if user and hasattr(user, 'free_uploads_used') else 0


def e(key: str) -> str:
    """
    اختصار لـ get_emoji — يرجع الحرف فقط للاستخدام في النصوص.
    مثال: f"{e('WAVE')} أهلاً"
    """
    return get_emoji(key)[0]
