from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def get_client_ip(request: Request) -> str | None:
    # Respeita proxy (Railway/Render) → 1º IP do X-Forwarded-For
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else None


def record_audit(
    db: Session,
    *,
    request: Request,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: int | None,
    autocommit: bool = False,
) -> None:
    """
    Se autocommit=False (padrão): inclui o log na MESMA transação do seu CRUD.
    Se autocommit=True: faz commit isolado só do log (bom para login/logout).
    """
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        timestamp_utc=datetime.now(UTC),
        ip=get_client_ip(request),
    )
    db.add(log)
    if autocommit:
        try:
            db.commit()
        except Exception:
            db.rollback()  # falha em log não deve derrubar o request
