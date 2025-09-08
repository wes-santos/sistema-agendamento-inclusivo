# scripts/clean.py
from __future__ import annotations

import argparse
import os
from collections.abc import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import get_db  # usa o provider do projeto (FastAPI) -> Session

DEFAULT_EXCLUSIONS = {"alembic_version"}  # preserva o estado das migrações


def get_session() -> Session:
    gen = get_db()
    return next(gen)  # type: ignore


def get_engine_from_session(db: Session) -> Engine:
    bind = db.get_bind()
    assert bind is not None, "No engine bind found on Session"
    return bind


def list_tables(engine: Engine, schema: str | None = None) -> list[str]:
    insp = inspect(engine)
    schema = schema or "public"
    return [t for t in insp.get_table_names(schema=schema)]


def truncate_all(
    db: Session,
    *,
    exclude: Iterable[str] = (),
    schema: str | None = None,
) -> None:
    """
    Executa TRUNCATE em todas as tabelas (exceto 'exclude'), com RESTART IDENTITY CASCADE.
    PostgreSQL only.
    """
    engine = get_engine_from_session(db)
    schema = schema or "public"

    tables = set(list_tables(engine, schema=schema))
    to_skip = set(exclude) | set(DEFAULT_EXCLUSIONS)
    target = sorted(t for t in tables if t not in to_skip)

    if not target:
        print("[clean] Não há tabelas para truncar (após exclusões).")
        return

    # Monta identificadores qualificados e escapados
    qualified = ", ".join(f'"{schema}"."{t}"' for t in target)
    sql = f"TRUNCATE {qualified} RESTART IDENTITY CASCADE;"

    print(f"[clean] Truncating tables ({len(target)}): {', '.join(target)}")
    db.execute(text(sql))
    db.commit()
    print("[clean] Concluído.")


def main():
    parser = argparse.ArgumentParser(
        description="Limpa dados de todas as tabelas (DEV/HML). Mantém alembic_version."
    )
    parser.add_argument(
        "--schema",
        default=os.getenv("DB_SCHEMA", "public"),
        help="Schema alvo (default: public ou $DB_SCHEMA).",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Lista de tabelas para NÃO limpar (ex.: users roles). 'alembic_version' já é preservada por padrão.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Não perguntar confirmação (útil para CI). Ou defina ALLOW_CLEAN=1.",
    )
    parser.add_argument(
        "--keep-users",
        action="store_true",
        help="Atalho para preservar tabelas comuns de identidade (users, roles, permissions).",
    )
    args = parser.parse_args()

    exclude = set(args.exclude)
    if args.keep_users:
        exclude |= {"users", "roles", "permissions", "user_roles"}

    require_confirm = not (args.yes or os.getenv("ALLOW_CLEAN") == "1")
    if require_confirm:
        print(
            "⚠️  ATENÇÃO: isso irá APAGAR TODOS os dados (TRUNCATE + RESTART IDENTITY) no schema "
            f"{args.schema!r}, exceto tabelas excluídas e 'alembic_version'."
        )
        resp = input("Digite 'LIMPAR' para confirmar: ").strip()
        if resp != "LIMPAR":
            print("[clean] Cancelado pelo usuário.")
            return

    db = get_session()
    truncate_all(db, exclude=exclude, schema=args.schema)


if __name__ == "__main__":
    main()
