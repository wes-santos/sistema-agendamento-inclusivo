"""appointment: add confirmed_at and cancellation_reason columns

Revision ID: 36e6adf2aea8
Revises: d675ba070ed1
Create Date: 2025-09-07 20:07:07.802139

"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "36e6adf2aea8"
down_revision: str | Sequence[str] | None = "d675ba070ed1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "appointments",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("cancellation_reason", sa.String(length=240), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("appointments", "cancellation_reason")
    op.drop_column("appointments", "confirmed_at")
