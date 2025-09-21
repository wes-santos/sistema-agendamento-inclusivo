"""Add STUDENT role and link students to user accounts

Revision ID: f4a9a21d8c5e
Revises: ee2014276ce2
Create Date: 2025-09-22 18:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a9a21d8c5e"
down_revision: str | Sequence[str] | None = "4a939b2c3851"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_ROLE = "STUDENT"
EXISTING_ROLES = ("FAMILY", "PROFESSIONAL", "COORDINATION")


def upgrade() -> None:
    # Ensure the new role exists in the enum
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                WHERE t.typname = 'role_enum' AND e.enumlabel = '{NEW_ROLE}'
            ) THEN
                EXECUTE format('ALTER TYPE role_enum ADD VALUE %L', '{NEW_ROLE}');
            END IF;
        END $$;
        """
    )

    # Add students.user_id referencing users.id
    op.add_column(
        "students",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_students_user_id_users",
        "students",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_students_user_id", "students", ["user_id"])


def downgrade() -> None:
    # Remove column/constraints first
    op.drop_constraint("uq_students_user_id", "students", type_="unique")
    op.drop_constraint("fk_students_user_id_users", "students", type_="foreignkey")
    op.drop_column("students", "user_id")

    # Ensure there are no users with the STUDENT role before dropping it
    conn = op.get_bind()
    count = conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE role = :role"),
        {"role": NEW_ROLE},
    ).scalar()

    if count and count > 0:
        raise RuntimeError(
            "Não é possível remover o valor 'STUDENT' enquanto existirem usuários com essa role."
        )

    # Recreate enum without STUDENT
    op.execute("ALTER TYPE role_enum RENAME TO role_enum_old")
    existing = ", ".join(repr(v) for v in EXISTING_ROLES)
    op.execute(f"CREATE TYPE role_enum AS ENUM ({existing})")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE role_enum USING role::text::role_enum"
    )
    op.execute("DROP TYPE role_enum_old")
