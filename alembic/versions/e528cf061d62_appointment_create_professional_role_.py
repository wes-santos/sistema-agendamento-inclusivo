"""appointment: create professional role index

Revision ID: e528cf061d62
Revises: d0d8c7e4379a
Create Date: 2025-09-06 15:32:31.448472

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e528cf061d62"
down_revision: str | Sequence[str] | None = "d0d8c7e4379a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_appt_professional_start",
        "appointments",
        ["professional_id", "start_at"],
        unique=False,
    )
    op.create_index(
        "ix_appt_prof_status_start",
        "appointments",
        ["professional_id", "status", "start_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_appt_prof_status_start", table_name="appointments")
    op.drop_index("ix_appt_professional_start", table_name="appointments")
