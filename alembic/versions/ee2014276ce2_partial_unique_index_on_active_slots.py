"""partial unique index on active slots

Revision ID: ee2014276ce2
Revises: 36e6adf2aea8
Create Date: 2025-09-11 22:44:09.288150

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee2014276ce2"
down_revision: str | Sequence[str] | None = "36e6adf2aea8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ux_appt_prof_start_active"


def upgrade() -> None:
    # 1) remover a UNIQUE CONSTRAINT de tabela (hoje: força unicidade para todos os status)
    op.drop_constraint("uq_appt_prof_start", "appointments", type_="unique")

    # 2) criar ÍNDICE ÚNICO PARCIAL: só vale para status ativos (SCHEDULED/CONFIRMED)
    op.create_index(
        INDEX_NAME,
        "appointments",
        ["professional_id", "starts_at"],
        unique=True,
        postgresql_where=sa.text("status IN ('SCHEDULED','CONFIRMED')"),
    )


def downgrade() -> None:
    # reverter: dropar índice parcial e recriar a UNIQUE constraint "cheia"
    op.drop_index(INDEX_NAME, table_name="appointments")
    op.create_unique_constraint(
        "uq_appt_prof_start",
        "appointments",
        ["professional_id", "starts_at"],
    )
