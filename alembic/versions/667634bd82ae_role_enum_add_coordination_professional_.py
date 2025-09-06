"""role_enum: add COORDINATION, PROFESSIONAL and FAMILY

Revision ID: 667634bd82ae
Revises: 663f34bb7879
Create Date: 2025-09-05 03:14:11.224686

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "667634bd82ae"
down_revision: str | Sequence[str] | None = "663f34bb7879"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_VALUES = ("FAMILY", "PROFESSIONAL", "COORDINATION")
PREV_VALUES = ("FAMILY", "PROFESSIONAL")  # estado para o qual o downgrade vai voltar


def upgrade():
    conn = op.get_bind()
    table = "users"

    # 1) Se o tipo não existir, cria já com todos os valores e garante que a coluna usa esse tipo
    type_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'role_enum'")
    ).scalar()
    if not type_exists:
        # cria o tipo com TODOS os valores
        op.execute(
            f"CREATE TYPE role_enum AS ENUM ({', '.join(repr(v) for v in NEW_VALUES)})"
        )
        # converte a coluna para role_enum (se ainda não for)
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN role TYPE role_enum USING role::text::role_enum"
        )
        return

    # 2) Se o tipo existe, adiciona cada valor que estiver faltando
    for label in NEW_VALUES:
        op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                WHERE t.typname = 'role_enum' AND e.enumlabel = '{label}'
            ) THEN
                -- usar EXECUTE + format(%L) garante citação correta
                EXECUTE format('ALTER TYPE role_enum ADD VALUE %L', '{label}');
            END IF;
        END $$;
        """)


def downgrade():
    conn = op.get_bind()
    table = "users"

    # Se houver valores fora do conjunto PREV_VALUES, mapeie ou bloqueie o downgrade
    invalid_count = conn.execute(
        sa.text(
            f"SELECT count(*) FROM {table} WHERE role::text NOT IN :prev"
        ).bindparams(sa.bindparam("prev", tuple(PREV_VALUES), expanding=True))
    ).scalar()

    if invalid_count and invalid_count > 0:
        # Se preferir mapear automatico, troque este raise por um UPDATE antes da conversão.
        raise RuntimeError(
            f"Downgrade bloqueado: {invalid_count} linha(s) com roles fora de {PREV_VALUES}. "
            f"Execute um UPDATE para normalizar (ex.: UPDATE {table} SET role='PROFESSIONAL' WHERE role='COORDINATION')."
        )

    # Recria o tipo somente com os valores anteriores
    # 1) cria um tipo temporário
    op.execute(
        f"CREATE TYPE role_enum_old AS ENUM ({', '.join(repr(v) for v in PREV_VALUES)})"
    )
    # 2) converte a coluna para o tipo temporário
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN role TYPE role_enum_old USING role::text::role_enum_old"
    )
    # 3) troca os tipos
    op.execute("DROP TYPE role_enum")
    op.execute("ALTER TYPE role_enum_old RENAME TO role_enum")
