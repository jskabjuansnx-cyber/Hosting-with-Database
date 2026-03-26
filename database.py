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
    has_uploaded_free = Column(Boolean, default=False)  # مجاني رفع قبل كده ولا لا
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
        ("users", "has_uploaded_free", "BOOLEAN DEFAULT 0"),
        ("users", "ban_reason",        "TEXT"),
        ("users", "subscription_expiry", "DATETIME"),
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
