from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db.session import get_db
from app.models.user import Role, User
from app.web.templating import render
from app.core.settings import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from sqlalchemy.orm import Session

router = APIRouter()

# ===== Session store simplificado (troque por seu provider) =====
# Em produção, guarde no Redis/DB. Aqui é só para demonstração.
_SESSIONS: dict[
    str, dict
] = {}  # token -> {"user_id":..., "role":..., "name":..., "exp": datetime}

SESSION_COOKIE = "session"
SESSION_TTL_MINUTES = 60 * 8  # 8h


def _issue_session(resp: Response, user: dict):
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "user_id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "exp": datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES),
    }
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=bool(settings.SECURE_COOKIES),
        samesite="lax",
        max_age=SESSION_TTL_MINUTES * 60,
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )


def _clear_session(resp: Response):
    resp.delete_cookie(SESSION_COOKIE, path="/")


def _get_user_from_cookie(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    data = _SESSIONS.get(token)
    if not data:
        return None
    if data["exp"] < datetime.utcnow():
        # expirou
        _SESSIONS.pop(token, None)
        return None
    return data


# ===== Auth real (DB) =====
def authenticate_user(db: Session, email: str, password: str) -> dict | None:
    user: User | None = db.query(User).filter(User.email == email).one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return {"id": user.id, "name": user.name, "role": user.role}


# ===== Auth demo (troque por sua autenticação real) =====
def _demo_auth(email: str, password: str) -> dict | None:
    # Permite alguns usuários de brincadeira
    demo_users = {
        "familia@demo": {"id": "u1", "name": "Família Demo", "role": Role.FAMILY},
        "prof@demo": {
            "id": "u2",
            "name": "Profissional Demo",
            "role": Role.PROFESSIONAL,
        },
        "coord@demo": {
            "id": "u3",
            "name": "Coordenação Demo",
            "role": Role.COORDINATION,
        },
    }
    if email in demo_users and password == "demo":
        u = demo_users[email]
        return {"id": u["id"], "name": u["name"], "role": u["role"]}
    return None


# EXEMPLO de como plugar na sua auth real:
# def authenticate_user(db: Session, email: str, password: str) -> Optional[dict]:
#     user = db.query(User).filter(User.email == email).first()
#     if not user: return None
#     if not verify_password(password, user.password_hash): return None
#     return {"id": user.id, "name": user.name, "role": user.role}

# ===== Rotas =====


@router.get("/login", response_class=HTMLResponse, name="auth_login_get")
def login_get(
    request: Request,
    next: str = Query("/", alias="next"),
    demo: bool = Query(False),
):
    ctx = {"next": next, "form": {"email": "familia@demo" if demo else ""}}
    return render(request, "pages/auth/login.html", ctx)


@router.post("/login", response_class=HTMLResponse, name="auth_login_post")
def login_post(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    demo: bool = Query(False),
    db: Session = Depends(get_db),
):
    # 1) autenticação real (DB)
    user = authenticate_user(db, email, password)
    # 2) fallback demo (se habilitado via query)
    if not user and demo:
        user = _demo_auth(email, password)

    if not user:
        ctx = {
            "error": "E-mail ou senha inválidos.",
            "next": next,
            "form": {"email": email},
        }
        return render(request, "pages/auth/login.html", ctx)

    # Defina cookies no PRÓPRIO objeto de resposta que será retornado
    target = next or "/"
    # Evita open-redirect: só permite caminhos relativos
    if "://" in target:
        target = "/"

    # Redireciona por role se 'next' for raiz ou vazio
    role = user.get("role")
    if not next or next == "/":
        if role == Role.COORDINATION:
            target = "/coordination/dashboard"
        elif role == Role.PROFESSIONAL:
            target = "/professional/dashboard"
        elif role == Role.FAMILY:
            target = "/family/dashboard"

    redirect = RedirectResponse(target, status_code=303)

    # Cookie de sessão (simplificado, para UI)
    _issue_session(redirect, user)

    # JWTs para integração com require_roles (via cookie access_token)
    access = create_access_token(str(user["id"]))
    refresh = create_refresh_token(str(user["id"]))
    cookie_kwargs = dict(
        httponly=True,
        secure=bool(settings.SECURE_COOKIES),
        samesite="lax",
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )
    redirect.set_cookie(
        key="access_token",
        value=access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )
    # refresh opcional (pode ser usado por endpoints de refresh futuramente)
    redirect.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **cookie_kwargs,
    )

    return redirect


@router.get("/logout", name="auth_logout")
def logout(request: Request, next: str = "/login"):
    # Limpa cookie na resposta de redirect e tenta invalidar o token em memória
    target = next or "/login"
    # apenas caminhos relativos seguros
    if not target.startswith("/"):
        target = "/login"
    # Evita loop de voltar para a mesma página protegida
    if target == request.url.path:
        target = "/login"

    redirect = RedirectResponse(target, status_code=303)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _SESSIONS.pop(token, None)
    _clear_session(redirect)
    # Remove também cookies de JWT se existirem
    for k in ("access_token", "refresh_token"):
        redirect.delete_cookie(k, path="/")
    return redirect


# ===== Helper para outros routers (se quiser usar) =====
def get_current_user_optional(request: Request) -> dict | None:
    return _get_user_from_cookie(request)
