"""create student role

Revision ID: 17408b14791c
Revises: 44ac4fa6b4d9
Create Date: 2025-09-06 21:22:34.351727

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "17408b14791c"
down_revision: str | Sequence[str] | None = "44ac4fa6b4d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = ("STUDENT", "PROFESSIONAL", "COORDINATION")
PREV_VALUES = ("FAMILY", "PROFESSIONAL", "COORDINATION")


def upgrade() -> None:
    """Upgrade schema."""

    table = "users"
    # Drop the old enum type
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text")
    op.execute("DROP TYPE role_enum")
    # Create the new enum type
    op.execute(
        f"CREATE TYPE role_enum AS ENUM ({', '.join(repr(v) for v in NEW_VALUES)})"
    )
    # Convert the column back to the new enum type
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN role TYPE role_enum USING role::text::role_enum"
    )


def downgrade() -> None:
    """Downgrade schema."""
    table = "users"
    # Change column to text and drop current enum
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text")
    op.execute("DROP TYPE role_enum")
    # Create the old enum type
    op.execute(
        f"CREATE TYPE role_enum AS ENUM ({', '.join(repr(v) for v in PREV_VALUES)})"
    )
    # Convert the column back to the old enum type
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN role TYPE role_enum USING role::text::role_enum"
    )
