"""reminder_24h_sent_at

Revision ID: 4a939b2c3851
Revises: ee2014276ce2
Create Date: 2025-09-12 20:25:30.106485

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a939b2c3851"
down_revision: str | Sequence[str] | None = "ee2014276ce2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_appointments_reminder_sent_at",
        "appointments",
        ["reminder_24h_sent_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_appointments_reminder_sent_at", table_name="appointments")
    op.drop_column("appointments", "reminder_24h_sent_at")
