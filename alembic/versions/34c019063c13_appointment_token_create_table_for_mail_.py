"""appointment_token: create table for mail integration

Revision ID: 34c019063c13
Revises: 44ac4fa6b4d9
Create Date: 2025-09-07 13:39:53.894414

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34c019063c13"
down_revision: str | Sequence[str] | None = "44ac4fa6b4d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    type_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'role_enum'")
    ).scalar()
    if not type_exists:
        # cria o tipo com TODOS os valores
        op.execute(
            "CREATE TYPE role_enum AS ENUM ("
            f"{', '.join(repr(v) for v in ('CONFIRM', 'CANCEL'))})"
        )
        op.execute(
            "ALTER TABLE appointment_tokens"
            "ALTER COLUMN role TYPE role_enum USING role::text::role_enum"
        )

    op.create_table(
        "appointment_tokens",
        sa.Column("token", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "CONFIRM", "CANCEL", name="appointment_token_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),  # UTC inside
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tokens_appointment_id", "appointment_tokens", ["appointment_id"]
    )
    op.create_index("ix_tokens_expires_at", "appointment_tokens", ["expires_at"])
    # índice parcial opcional (ativo por tipo não-consumido) — Postgres:
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_token_per_appt_kind
        ON appointment_tokens (appointment_id, kind)
        WHERE consumed_at IS NULL;
    """)


def downgrade() -> None:
    op.drop_index("uq_active_token_per_appt_kind")
    op.drop_index("ix_tokens_expires_at", table_name="appointment_tokens")
    op.drop_index("ix_tokens_appointment_id", table_name="appointment_tokens")
    op.execute(
        "ALTER TABLE vappointment_tokens ALTER COLUMN role TYPE text USING role::text"
    )
    op.execute("DROP TYPE IF EXISTS appointment_token_kind;")
    op.drop_table("appointment_tokens")
