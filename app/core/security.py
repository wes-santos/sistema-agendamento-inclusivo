from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.settings import settings

pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


_PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")


def validate_password_policy(password: str) -> None:
    """Raises ValueError if password does not meet policy.
    Policy: ≥8 chars, at least one upper, one lower, one digit, one special.
    """
    if not _PASSWORD_REGEX.match(password or ""):
        raise ValueError(
            "Senha fraca: mínimo 8 caracteres, com maiúscula, minúscula, dígito e caractere especial."  # noqa: E501
        )


def _now() -> datetime:
    return datetime.now(UTC)


def create_token(sub: str, type_: str, expires_delta: timedelta) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": sub,  # user id (string)
        "type": type_,  # "access" | "refresh"
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def create_access_token(sub: str) -> str:
    return create_token(
        sub, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(sub: str) -> str:
    return create_token(
        sub, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except JWTError as e:
        raise ValueError("Token inválido.") from e
    if payload.get("type") != expected_type:
        raise ValueError("Tipo de token inválido.")
    return payload


class CSPMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response: Response = await call_next(request)

        csp = (
            "default-src 'self'; "
            f"style-src 'self' 'nonce-{nonce}'; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["Content-Security-Policy"] = csp
        return response
