from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.settings import Settings, TokenPair, settings
from app.db import get_db
from app.models.user import User
from app.schemas.auth import LoginIn, LoginOut


router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(resp: Response, access: str, refresh: str) -> None:
    cookie_kwargs = dict(
        httponly=True,
        secure=bool(settings.SECURE_COOKIES),
        samesite="lax",
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )
    resp.set_cookie(
        key="access_token",
        value=access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )
    resp.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **cookie_kwargs,
    )


@router.post("/login", response_model=LoginOut)
def api_login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    user: User | None = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))

    # Optionally set HttpOnly cookies (useful for frontends)
    if settings.USE_COOKIE_AUTH:
        _set_auth_cookies(response, access, refresh)

    return LoginOut(access_token=access, refresh_token=refresh, token_type="bearer")


@router.get("/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    # Reuse dependency logic from app.deps by importing lazily to avoid cycles
    from app.deps import get_current_user

    user = get_current_user(request, db)  # raises 401 appropriately
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": getattr(user.role, "value", str(user.role)),
        "is_active": user.is_active,
    }


@router.post("/logout")
def api_logout(response: Response):
    # Clear auth cookies (JWTs are stateless; this only affects cookie-based flows)
    for k in ("access_token", "refresh_token"):
        response.delete_cookie(k, path="/")
    return {"ok": True}


@router.post("/refresh", response_model=LoginOut)
def api_refresh(request: Request) -> LoginOut:
    # Expect refresh token in Authorization: Bearer <token> or cookie
    auth = request.headers.get("Authorization")
    token: str | None = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
    if not token:
        token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    try:
        payload = decode_token(token, expected_type="refresh")
    except ValueError:
        raise HTTPException(status_code=401, detail="Refresh token inválido") from ValueError

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Refresh token malformado")

    access = create_access_token(str(sub))
    refresh = create_refresh_token(str(sub))
    return LoginOut(access_token=access, refresh_token=refresh)

