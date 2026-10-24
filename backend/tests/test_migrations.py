import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text

import database
from database import Base, init_db

# The schema exactly as the original create_all() produced it
LEGACY_DDL = """
CREATE TABLE users (email VARCHAR PRIMARY KEY, name VARCHAR NOT NULL,
                    password_hash VARCHAR NOT NULL, created_at DATETIME);
CREATE TABLE profiles (id VARCHAR PRIMARY KEY, user_email VARCHAR NOT NULL, name VARCHAR NOT NULL,
                       color VARCHAR, icon VARCHAR, created_at DATETIME);
CREATE TABLE watch_history (id VARCHAR PRIMARY KEY, user_email VARCHAR NOT NULL,
                            profile_id VARCHAR NOT NULL, history TEXT, updated_at DATETIME);
CREATE TABLE continue_watching (id VARCHAR PRIMARY KEY, user_email VARCHAR NOT NULL,
                                profile_id VARCHAR NOT NULL, items TEXT, updated_at DATETIME);
CREATE TABLE watch_again (id VARCHAR PRIMARY KEY, user_email VARCHAR NOT NULL,
                          profile_id VARCHAR NOT NULL, items TEXT, updated_at DATETIME);
CREATE TABLE watch_invites (id VARCHAR PRIMARY KEY, from_email VARCHAR NOT NULL,
                            from_name VARCHAR NOT NULL, to_email VARCHAR NOT NULL,
                            movie_title VARCHAR NOT NULL, movie_id VARCHAR NOT NULL,
                            room_id VARCHAR NOT NULL, status VARCHAR, created_at DATETIME);
CREATE TABLE watch_rooms (room_id VARCHAR PRIMARY KEY, movie_id VARCHAR NOT NULL,
                          movie_title VARCHAR NOT NULL, created_by VARCHAR NOT NULL, created_at DATETIME);
"""

LEGACY_ROWS = """
INSERT INTO users VALUES ('alice@example.com', 'Alice', 'hash', '2025-01-01');
INSERT INTO users VALUES ('bob@example.com', 'Bob', 'hash', '2025-01-01');
INSERT INTO profiles VALUES ('p-alice', 'alice@example.com', 'Main', '#e50914', 'x', '2025-01-01');
INSERT INTO profiles VALUES ('p-bob', 'bob@example.com', 'Main', '#e50914', 'x', '2025-01-01');
-- orphan: account deleted
INSERT INTO profiles VALUES ('p-ghost', 'ghost@example.com', 'Main', '#e50914', 'x', '2025-01-01');

INSERT INTO watch_history VALUES ('h1', 'alice@example.com', 'p-alice', '["old"]', '2025-01-01');
INSERT INTO watch_history VALUES ('h2', 'alice@example.com', 'p-alice', '["new"]', '2025-02-01');
INSERT INTO watch_history VALUES ('h3', 'bob@example.com', 'p-bob', '["bob"]', '2025-01-01');
-- orphan left behind by the old profile delete, which only removed history
INSERT INTO continue_watching VALUES ('c1', 'alice@example.com', 'p-deleted', '[]', '2025-01-01');
-- row claiming another account's profile
INSERT INTO watch_again VALUES ('w1', 'alice@example.com', 'p-bob', '[]', '2025-01-01');
INSERT INTO watch_again VALUES ('w2', 'bob@example.com', 'p-bob', '["keep"]', '2025-01-01');

INSERT INTO watch_rooms VALUES ('room-1', 'm1', 'Movie', 'alice@example.com', '2025-01-01');
INSERT INTO watch_rooms VALUES ('room-ghost', 'm1', 'Movie', 'ghost@example.com', '2025-01-01');
INSERT INTO watch_invites VALUES ('i1', 'alice@example.com', 'Alice', 'bob@example.com', 'Movie', 'm1', 'room-1', 'pending', '2025-01-01');
INSERT INTO watch_invites VALUES ('i2', 'alice@example.com', 'Alice', 'ghost@example.com', 'Movie', 'm1', 'room-1', 'pending', '2025-01-01');
INSERT INTO watch_invites VALUES ('i3', 'bob@example.com', 'Bob', 'alice@example.com', 'Movie', 'm1', 'room-ghost', 'pending', '2025-01-01');
"""


def make_engine(path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def rows(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).fetchall()


def run_alembic(engine, action, revision):
    with engine.begin() as connection:
        getattr(command, action)(database._alembic_config(connection), revision)


@pytest.fixture
def fresh_engine(tmp_path):
    engine = make_engine(tmp_path / "fresh.db")
    yield engine
    engine.dispose()


@pytest.fixture
def legacy_engine(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as raw:
        raw.executescript(LEGACY_DDL + LEGACY_ROWS)
    engine = make_engine(path)
    yield engine
    engine.dispose()


def test_migrations_produce_exactly_the_model_schema(fresh_engine):
    init_db(fresh_engine)

    with fresh_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_migrations_downgrade_and_upgrade_cleanly(fresh_engine):
    init_db(fresh_engine)
    run_alembic(fresh_engine, "downgrade", "base")
    assert set(inspect(fresh_engine).get_table_names()) == {"alembic_version"}

    init_db(fresh_engine)
    assert "users" in inspect(fresh_engine).get_table_names()


def test_init_db_is_idempotent(fresh_engine):
    init_db(fresh_engine)
    init_db(fresh_engine)
    assert rows(fresh_engine, "SELECT version_num FROM alembic_version") == [("0002_relational_constraints",)]


def test_legacy_database_is_stamped_and_cleaned(legacy_engine):
    init_db(legacy_engine)

    assert rows(legacy_engine, "SELECT version_num FROM alembic_version") == [
        ("0002_relational_constraints",)
    ]
    assert rows(legacy_engine, "SELECT id FROM profiles ORDER BY id") == [("p-alice",), ("p-bob",)]
    # newest history row per profile survives
    assert rows(legacy_engine, "SELECT id, history FROM watch_history ORDER BY id") == [
        ("h2", '["new"]'),
        ("h3", '["bob"]'),
    ]
    assert rows(legacy_engine, "SELECT id FROM continue_watching") == []
    assert rows(legacy_engine, "SELECT id FROM watch_again") == [("w2",)]
    assert rows(legacy_engine, "SELECT room_id FROM watch_rooms") == [("room-1",)]
    assert rows(legacy_engine, "SELECT id FROM watch_invites") == [("i1",)]


def test_constraints_are_enforced_after_migration(legacy_engine):
    init_db(legacy_engine)

    with pytest.raises(Exception, match="UNIQUE"):
        with legacy_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO watch_history VALUES ('h9', 'alice@example.com', 'p-alice', '[]', NULL)")
            )
    with pytest.raises(Exception, match="FOREIGN KEY"):
        with legacy_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO profiles VALUES ('p9', 'nobody@example.com', 'X', NULL, NULL, NULL)")
            )


def test_deleting_an_account_cascades(legacy_engine):
    init_db(legacy_engine)

    with legacy_engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE email = 'alice@example.com'"))

    assert rows(legacy_engine, "SELECT id FROM profiles") == [("p-bob",)]
    assert rows(legacy_engine, "SELECT id FROM watch_history") == [("h3",)]
    assert rows(legacy_engine, "SELECT room_id FROM watch_rooms") == []
    assert rows(legacy_engine, "SELECT id FROM watch_invites") == []


def test_unknown_unversioned_schema_is_not_stamped(tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE something_else (id INTEGER PRIMARY KEY)")
    engine = make_engine(path)

    with pytest.raises(RuntimeError, match="Refusing to stamp"):
        init_db(engine)
    engine.dispose()


def test_deleting_a_profile_through_the_api_leaves_no_rows(client, alice):
    """The app's own schema (built from the models) also cascades."""
    pid = alice["profile_id"]
    client.post("/history/save", json={"profile_id": pid, "history": []}, headers=alice["headers"])

    with database.SessionLocal() as db:
        db.execute(text("DELETE FROM profiles WHERE id = :pid"), {"pid": pid})
        db.commit()
        assert db.execute(text("SELECT COUNT(*) FROM watch_history")).scalar() == 0
