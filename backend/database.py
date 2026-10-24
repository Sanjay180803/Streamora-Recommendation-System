import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{Path(settings.data_dir, 'streamora.db').as_posix()}",
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine       = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):
        # SQLite ignores foreign keys (and ON DELETE CASCADE) unless enabled per connection
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _user_fk():
    return ForeignKey("users.email", ondelete="CASCADE")


def _profile_fk():
    return ForeignKey("profiles.id", ondelete="CASCADE")


class User(Base):
    __tablename__ = "users"
    email         = Column(String, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)


class Profile(Base):
    __tablename__ = "profiles"
    id         = Column(String, primary_key=True)
    user_email = Column(String, _user_fk(), nullable=False, index=True)
    name       = Column(String, nullable=False)
    color      = Column(String, default="#e50914")
    icon       = Column(String, default="🎬")
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_watch_history_profile"),)
    id         = Column(String, primary_key=True)
    user_email = Column(String, _user_fk(), nullable=False, index=True)
    profile_id = Column(String, _profile_fk(), nullable=False, index=True)
    history    = Column(Text, default="[]")
    updated_at = Column(DateTime, default=datetime.utcnow)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_continue_watching_profile"),)
    id         = Column(String, primary_key=True)
    user_email = Column(String, _user_fk(), nullable=False, index=True)
    profile_id = Column(String, _profile_fk(), nullable=False, index=True)
    items      = Column(Text, default="[]")  # JSON array of {movie, progress}
    updated_at = Column(DateTime, default=datetime.utcnow)


class WatchAgain(Base):
    __tablename__ = "watch_again"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_watch_again_profile"),)
    id         = Column(String, primary_key=True)
    user_email = Column(String, _user_fk(), nullable=False, index=True)
    profile_id = Column(String, _profile_fk(), nullable=False, index=True)
    items      = Column(Text, default="[]")  # JSON array of movies
    updated_at = Column(DateTime, default=datetime.utcnow)


class WatchRoom(Base):
    __tablename__ = "watch_rooms"
    room_id     = Column(String, primary_key=True)
    movie_id    = Column(String, nullable=False)
    movie_title = Column(String, nullable=False)
    created_by  = Column(String, _user_fk(), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)


class WatchInvite(Base):
    __tablename__ = "watch_invites"
    id          = Column(String, primary_key=True)
    from_email  = Column(String, _user_fk(), nullable=False)
    from_name   = Column(String, nullable=False)
    to_email    = Column(String, _user_fk(), nullable=False)
    movie_title = Column(String, nullable=False)
    movie_id    = Column(String, nullable=False)
    room_id     = Column(String, ForeignKey("watch_rooms.room_id", ondelete="CASCADE"), nullable=False)
    status      = Column(String, default="pending")
    created_at  = Column(DateTime, default=datetime.utcnow)


# ── Migrations ────────────────────────────────────────────────────────────────
BASELINE_REVISION = "0001_baseline"

# Tables and columns created by the original create_all() schema, before
# migrations existed. A database matching this exactly can be stamped safely.
BASELINE_SCHEMA = {
    "users": {"email", "name", "password_hash", "created_at"},
    "profiles": {"id", "user_email", "name", "color", "icon", "created_at"},
    "watch_history": {"id", "user_email", "profile_id", "history", "updated_at"},
    "continue_watching": {"id", "user_email", "profile_id", "items", "updated_at"},
    "watch_again": {"id", "user_email", "profile_id", "items", "updated_at"},
    "watch_invites": {
        "id", "from_email", "from_name", "to_email", "movie_title",
        "movie_id", "room_id", "status", "created_at",
    },
    "watch_rooms": {"room_id", "movie_id", "movie_title", "created_by", "created_at"},
}


def _alembic_config(connection):
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["connection"] = connection
    return config


def _is_unversioned_baseline(connection) -> bool:
    """True for a database created by the pre-migration create_all() schema."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables or not tables:
        return False
    actual = {t: {c["name"] for c in inspector.get_columns(t)} for t in tables}
    if actual != BASELINE_SCHEMA:
        raise RuntimeError(
            "The database has tables but no migration history, and its schema does "
            "not match the original Streamora schema. Refusing to stamp it; inspect "
            f"{connection.engine.url!r} manually."
        )
    return True


def init_db(bind=None):
    """Bring the database schema up to date with Alembic migrations."""
    from alembic import command

    bind = bind or engine
    if bind.dialect.name == "sqlite" and bind.url.database:
        Path(bind.url.database).parent.mkdir(parents=True, exist_ok=True)

    with bind.begin() as connection:
        config = _alembic_config(connection)
        if _is_unversioned_baseline(connection):
            logger.info("Existing pre-migration database detected; stamping baseline revision")
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
