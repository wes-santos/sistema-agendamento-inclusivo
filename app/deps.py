from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.core.settings import settings

# Your existing DB session dependency here
from app.db import get_db
from app.models.user import Role, User


def _extract_token_from_request(request: Request) -> str | None:
    # Priority: Authorization header, then cookie (if enabled)
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
    if settings.USE_COOKIE_AUTH:
        return request.cookies.get("access_token")
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:  # noqa: B008
    token = _extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado"
        )

    try:
        payload = decode_token(token, expected_type="access")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        ) from ValueError

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado"
        )

    user: User | None = db.query(User).get(int(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário inativo ou inexistente",
        )

    return user


def require_roles(*allowed: Role) -> Callable[[Request, Session], User]:
    def wrapper(request: Request, db: Session = Depends(get_db)) -> User:  # noqa: B008
        user = get_current_user(request, db)
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão"
            )
        return user

    return wrapper
