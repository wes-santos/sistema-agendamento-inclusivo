"""professional: add user_id column

Revision ID: d675ba070ed1
Revises: 34c019063c13
Create Date: 2025-09-07 15:52:26.482391

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d675ba070ed1"
down_revision: str | Sequence[str] | None = "34c019063c13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("professionals", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_professionals_user_id", "professionals", ["user_id"])
    op.create_unique_constraint(
        "uq_professionals_user_id", "professionals", ["user_id"]
    )
    op.create_foreign_key(
        "fk_professionals_user_id",
        "professionals",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_professionals_user_id", "professionals", type_="foreignkey")
    op.drop_constraint("uq_professionals_user_id", "professionals", type_="unique")
    op.drop_index("ix_professionals_user_id", table_name="professionals")
    op.drop_column("professionals", "user_id")
