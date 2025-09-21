from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from fastapi import APIRouter, Body, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.db.session import get_db
from app.models.user import Role, User
from app.models.professional import Professional
from app.web.templating import render
from app.core.settings import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.email.render import render as render_email
from app.services.mailer import send_email
from sqlalchemy.exc import IntegrityError
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
    registered: bool = Query(False),
):
    flashes: list[dict] = []
    if registered:
        flashes.append(
            {
                "type": "success",
                "title": "Cadastro concluído",
                "message": "Sua conta foi criada. Entre com suas credenciais.",
            }
        )

    prefill_email = request.query_params.get("email") or ("familia@demo" if demo else "")

    ctx = {
        "next": next,
        "form": {"email": prefill_email},
        "flashes": flashes,
    }
    return render(request, "pages/auth/login.html", ctx)


@router.post("/login", response_class=HTMLResponse, name="auth_login_post")
def login_post(
    request: Request,
    response: Response,
    email: str | None = Form(None),
    password: str | None = Form(None),
    next: str = Form("/"),
    demo: bool = Query(False),
    db: Session = Depends(get_db),
    json_body: dict | None = Body(None),
):
    # Support JSON payloads (Insomnia/Postman)
    if (email is None or password is None) and isinstance(json_body, dict):
        email = json_body.get("email")
        password = json_body.get("password")

    if not email or not password:
        # If client expects JSON, return 400 JSON
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(
                {"detail": "email e senha são obrigatórios"}, status_code=400
            )
        ctx = {
            "error": "Informe e‑mail e senha.",
            "next": next,
            "form": {"email": email or ""},
        }
        return render(request, "pages/auth/login.html", ctx)
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

    # JWTs
    access = create_access_token(str(user["id"]))
    refresh = create_refresh_token(str(user["id"]))

    # If client wants JSON (API usage), return tokens instead of redirect
    accept = (request.headers.get("accept") or "").lower()
    if (
        "application/json" in accept
        or request.headers.get("x-requested-with") == "XMLHttpRequest"
    ):
        # Optionally also set cookies to help browser clients
        cookie_kwargs = dict(
            httponly=True,
            secure=bool(settings.SECURE_COOKIES),
            samesite="lax",
            path="/",
            domain=settings.COOKIE_DOMAIN or None,
        )
        response.set_cookie(
            key="access_token",
            value=access,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            **cookie_kwargs,
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            **cookie_kwargs,
        )
        return JSONResponse(
            {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}
        )

    redirect = RedirectResponse(target, status_code=303)
    # Cookie de sessão (simplificado, para UI)
    _issue_session(redirect, user)
    # Também propaga JWTs para páginas que usam cookies
    cookie_kwargs = dict(
        httponly=True,
        secure=bool(settings.SECURE_COOKIES),
        samesite="lax",
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )
    redirect.set_cookie(
        "access_token",
        access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )
    redirect.set_cookie(
        "refresh_token",
        refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **cookie_kwargs,
    )
    return redirect


def _role_options() -> list[dict[str, str]]:
    return [
        {"value": Role.FAMILY.value, "label": "Responsável (Família)"},
        {"value": Role.PROFESSIONAL.value, "label": "Profissional"},
    ]


@router.get("/register", response_class=HTMLResponse, name="auth_register_get")
def register_get(request: Request) -> HTMLResponse:
    ctx = {
        "role_options": _role_options(),
        "form": {"name": "", "email": "", "role": Role.FAMILY.value, "specialty": ""},
        "errors": {},
    }
    return render(request, "pages/auth/register.html", ctx)


@router.post("/register", response_class=HTMLResponse, name="auth_register_post")
def register_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    role: str = Form(...),
    specialty: str | None = Form(None),
    db: Session = Depends(get_db),
):
    name_clean = (name or "").strip()
    email_clean = (email or "").strip().lower()
    role_value = (role or "").strip().upper()
    specialty_clean = (specialty or "").strip() or None

    form_data = {
        "name": name_clean,
        "email": email_clean,
        "role": role_value,
        "specialty": specialty_clean or "",
    }
    errors: dict[str, str] = {}

    if not name_clean:
        errors["name"] = "Informe o nome completo."

    if not email_clean:
        errors["email"] = "Informe o e-mail."

    allowed_roles = {Role.FAMILY.value, Role.PROFESSIONAL.value}
    if role_value not in allowed_roles:
        errors["role"] = "Selecione um perfil válido."

    if not password:
        errors["password"] = "Informe uma senha."
    elif password != password_confirm:
        errors["password_confirm"] = "As senhas não coincidem."
    else:
        try:
            validate_password_policy(password)
        except ValueError as exc:
            errors["password"] = str(exc)

    if errors:
        ctx = {
            "role_options": _role_options(),
            "form": form_data,
            "errors": errors,
        }
        return render(request, "pages/auth/register.html", ctx)

    password_hash = hash_password(password)
    role_enum = Role(role_value)

    user = User(
        name=name_clean,
        email=email_clean,
        password_hash=password_hash,
        role=role_enum,
        is_active=True,
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        errors["email"] = "Já existe uma conta com este e-mail."
        ctx = {
            "role_options": _role_options(),
            "form": form_data,
            "errors": errors,
        }
        return render(request, "pages/auth/register.html", ctx)

    if role_enum == Role.PROFESSIONAL:
        professional = Professional(
            name=name_clean,
            user_id=user.id,
            speciality=specialty_clean,
            is_active=True,
        )
        db.add(professional)

    db.commit()

    login_url = request.url_for("auth_login_get")
    try:
        html = render_email("welcome.html").render(
            {"name": name_clean, "email": email_clean, "login_url": login_url}
        )
        send_email("[SAI] Boas-vindas", [email_clean], html, text=None)
    except Exception as email_error:  # pragma: no cover - best effort
        print(f"Failed to send welcome email: {email_error}")

    email_param = quote_plus(email_clean)
    return RedirectResponse(
        url=f"/login?registered=1&email={email_param}",
        status_code=303,
    )


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
