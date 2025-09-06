"""appointment: create new indexes

Revision ID: c9f847550338
Revises: e528cf061d62
Create Date: 2025-09-06 15:50:05.683680

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f847550338"
down_revision: str | Sequence[str] | None = "e528cf061d62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_appt_start", "appointments", ["start_at"], unique=False)
    op.create_index(
        "ix_appt_status_start", "appointments", ["status", "start_at"], unique=False
    )
    op.create_index("ix_appt_service", "appointments", ["service"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_appt_service", table_name="appointments")
    op.drop_index("ix_appt_status_start", table_name="appointments")
    op.drop_index("ix_appt_start", table_name="appointments")
