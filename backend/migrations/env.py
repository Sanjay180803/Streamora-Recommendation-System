"""Alembic environment.

database.init_db() passes an open connection through config.attributes;
the alembic CLI falls back to database.engine (configured by DATABASE_URL).
"""

from alembic import context

from database import Base, engine

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER constraints; batch mode rebuilds tables instead
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with engine.begin() as connection:
        _run(connection)
