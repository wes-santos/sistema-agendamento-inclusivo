from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.core.settings import settings
from app.deps import get_current_user, get_db, require_roles
from app.models.user import Role, User
from app.schemas.auth import LoginIn, LoginOut
from app.schemas.user import UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


# Helper: set/unset cookies when USE_COOKIE_AUTH is True
COOKIE_MAX_AGE_ACCESS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
COOKIE_MAX_AGE_REFRESH = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    if not settings.USE_COOKIE_AUTH:
        return
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN,
        max_age=COOKIE_MAX_AGE_ACCESS,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN,
        max_age=COOKIE_MAX_AGE_REFRESH,
        path="/auth/refresh",
    )


def _delete_auth_cookies(resp: Response, secure: bool = False):
    if not settings.USE_COOKIE_AUTH:
        return
    resp.delete_cookie(
        "access_token", path="/", samesite="lax", secure=secure, httponly=True
    )
    resp.delete_cookie(
        "refresh_token", path="/", samesite="lax", secure=secure, httponly=True
    )
    # resp.delete_cookie("csrf_token", path="/", samesite="lax", secure=secure)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)):  # noqa: B008
    # simple example; in prod validate uniqueness & email confirmation flows
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    try:
        validate_password_policy(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from ValueError

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):  # noqa: B008
    user: User | None = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas"
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuário inativo")

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))

    _set_auth_cookies(response, access, refresh)

    # If using cookies only, you can omit returning the tokens
    return LoginOut(
        access_token=None if settings.USE_COOKIE_AUTH else access,
        refresh_token=None if settings.USE_COOKIE_AUTH else refresh,
    )


@router.api_route(
    "/logout",
    methods=["GET", "POST"],
    name="logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(request: Request):
    next_url = request.query_params.get("next") or "/ui/login"
    resp = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)

    # limpa cookies de auth
    secure = request.url.scheme == "https"
    _delete_auth_cookies(resp, secure=secure)

    # zera a sessão, mas deixa um flash para feedback
    try:
        request.session.clear()
        request.session["flash"] = "Você saiu com sucesso."
    except Exception:
        pass

    return resp


@router.post("/refresh", response_model=LoginOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):  # noqa: B008
    # Support refresh via cookie OR Authorization header
    token = request.cookies.get("refresh_token") if settings.USE_COOKIE_AUTH else None
    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]

    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    try:
        payload = decode_token(token, expected_type="refresh")
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Refresh token inválido ou expirado"
        ) from ValueError

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token malformado")

    user: User | None = db.query(User).get(int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário inativo ou inexistente")

    access = create_access_token(str(user.id))
    refresh_new = create_refresh_token(str(user.id))

    _set_auth_cookies(response, access, refresh_new)

    return LoginOut(
        access_token=None if settings.USE_COOKIE_AUTH else access,
        refresh_token=None if settings.USE_COOKIE_AUTH else refresh_new,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):  # noqa: B008
    return user


@router.get("/only-coordination")
def only_coordination(
    user: User = Depends(require_roles(Role.COORDINATION)),
):
    return {"ok": True, "user_role": user.role}


@router.get("/only-professional")
def only_professional(
    user: User = Depends(require_roles(Role.PROFESSIONAL)),
):
    return {"ok": True, "user_role": user.role}


@router.get("/only-family")
def only_family(
    user: User = Depends(require_roles(Role.FAMILY)),
):
    return {"ok": True, "user_role": user.role}
