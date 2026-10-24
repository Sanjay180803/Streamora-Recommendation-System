"""Add foreign keys, cascades and one-row-per-profile constraints

Revision ID: 0002_relational_constraints
Revises: 0001_baseline
Create Date: 2026-10-24

Before adding constraints, rows that would violate them are removed:
  - profiles whose account no longer exists
  - list rows whose profile is missing or belongs to a different account
  - all but the most recently updated list row per profile
  - rooms whose creator is gone, and invites with a missing user or room

Tables are altered parents-first. On SQLite, batch mode rebuilds a table to
change its constraints; rebuilding a table that other tables already reference
with ON DELETE CASCADE would delete the referencing rows.
"""
from alembic import op

revision = "0002_relational_constraints"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

LIST_TABLES = ("watch_history", "continue_watching", "watch_again")


def _remove_rows_that_violate_constraints() -> None:
    op.execute("DELETE FROM profiles WHERE user_email NOT IN (SELECT email FROM users)")

    for table in LIST_TABLES:
        op.execute(f"""
            DELETE FROM {table}
            WHERE NOT EXISTS (
                SELECT 1 FROM profiles
                WHERE profiles.id = {table}.profile_id
                  AND profiles.user_email = {table}.user_email
            )
        """)
        op.execute(f"""
            DELETE FROM {table} WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY profile_id ORDER BY updated_at DESC, id DESC
                    ) AS row_number
                    FROM {table}
                ) ranked
                WHERE row_number > 1
            )
        """)

    op.execute("DELETE FROM watch_rooms WHERE created_by NOT IN (SELECT email FROM users)")
    op.execute("""
        DELETE FROM watch_invites
        WHERE from_email NOT IN (SELECT email FROM users)
           OR to_email NOT IN (SELECT email FROM users)
           OR room_id NOT IN (SELECT room_id FROM watch_rooms)
    """)


def upgrade() -> None:
    _remove_rows_that_violate_constraints()

    with op.batch_alter_table("profiles") as batch:
        batch.create_foreign_key(
            "fk_profiles_user_email", "users", ["user_email"], ["email"], ondelete="CASCADE"
        )

    for table in LIST_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                f"fk_{table}_user_email", "users", ["user_email"], ["email"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                f"fk_{table}_profile_id", "profiles", ["profile_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_unique_constraint(f"uq_{table}_profile", ["profile_id"])

    with op.batch_alter_table("watch_rooms") as batch:
        batch.create_foreign_key(
            "fk_watch_rooms_created_by", "users", ["created_by"], ["email"], ondelete="CASCADE"
        )

    with op.batch_alter_table("watch_invites") as batch:
        batch.create_foreign_key(
            "fk_watch_invites_from_email", "users", ["from_email"], ["email"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_watch_invites_to_email", "users", ["to_email"], ["email"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_watch_invites_room_id", "watch_rooms", ["room_id"], ["room_id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    # Children first, so no table is rebuilt while others still reference it
    with op.batch_alter_table("watch_invites") as batch:
        batch.drop_constraint("fk_watch_invites_room_id", type_="foreignkey")
        batch.drop_constraint("fk_watch_invites_to_email", type_="foreignkey")
        batch.drop_constraint("fk_watch_invites_from_email", type_="foreignkey")

    with op.batch_alter_table("watch_rooms") as batch:
        batch.drop_constraint("fk_watch_rooms_created_by", type_="foreignkey")

    for table in LIST_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_profile", type_="unique")
            batch.drop_constraint(f"fk_{table}_profile_id", type_="foreignkey")
            batch.drop_constraint(f"fk_{table}_user_email", type_="foreignkey")

    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("fk_profiles_user_email", type_="foreignkey")
