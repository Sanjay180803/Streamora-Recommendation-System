"""Baseline: the schema originally created by Base.metadata.create_all()

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-24

Existing databases created before migrations were introduced match this
revision and are stamped (not re-created) by database.init_db().
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

LIST_TABLES = {"watch_history": "history", "continue_watching": "items", "watch_again": "items"}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String()),
        sa.Column("icon", sa.String()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_profiles_user_email", "profiles", ["user_email"])

    for table, data_column in LIST_TABLES.items():
        op.create_table(
            table,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_email", sa.String(), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column(data_column, sa.Text()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index(f"ix_{table}_user_email", table, ["user_email"])
        op.create_index(f"ix_{table}_profile_id", table, ["profile_id"])

    op.create_table(
        "watch_invites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("from_email", sa.String(), nullable=False),
        sa.Column("from_name", sa.String(), nullable=False),
        sa.Column("to_email", sa.String(), nullable=False),
        sa.Column("movie_title", sa.String(), nullable=False),
        sa.Column("movie_id", sa.String(), nullable=False),
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("status", sa.String()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "watch_rooms",
        sa.Column("room_id", sa.String(), primary_key=True),
        sa.Column("movie_id", sa.String(), nullable=False),
        sa.Column("movie_title", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    for table in ("watch_rooms", "watch_invites", *LIST_TABLES, "profiles", "users"):
        op.drop_table(table)
