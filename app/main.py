from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

import app.db.base
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard_coordination import (
    router as dashboard_coordination_router,
)
from app.api.routes.dashboard_student import router as dashboard_student_router
from app.api.routes.dashboard_professional import (
    router as dashboard_professional_router,
)
from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.deps import get_current_user
from app.middlewares.telemetry import RequestContextMiddleware
from app.models.user import Role, User
from app.version import APP_VERSION, BUILD_TIME_UTC, GIT_SHA
from app.web.routes.ui import router as ui_router

configure_logging(json=True, level="INFO")

app = FastAPI(debug=settings.DEBUG)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")
templates.env.auto_reload = True
templates.env.cache = {}

# --- Middlewares de contexto/log
app.add_middleware(RequestContextMiddleware)

# --- CORS (config abaixo)
allowed_origins = []
for host in settings.ALLOWED_HOSTS.split(","):
    _host = host.strip()
    if not _host:
        continue
    # aceita tanto com quanto sem protocolo
    if _host.startswith("http"):
        allowed_origins.append(_host)
    else:
        allowed_origins.append(f"http://{_host}")
        allowed_origins.append(f"https://{_host}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"] if settings.DEBUG else allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Segurança: HTTPS only em prod
if settings.APP_ENV.value == "prod":
    app.add_middleware(HTTPSRedirectMiddleware)


# --- Security headers (HSTS, X-Content-Type-Options, etc.)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)

    # HSTS (apenas em HTTPS/prod)
    if settings.APP_ENV.value == "prod":
        # 6 meses + inclui subdomínios; ajuste se usar CDN
        response.headers["Strict-Transport-Security"] = (
            "max-age=15552000; includeSubDomains; preload"
        )

    # Defesa básica
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )
    # CSP simples; ajuste se usar JS/CSS externos
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    return response


# --- Trust proxy headers (se estiver atrás de proxy na cloud)
@app.middleware("http")
async def proxy_headers(request: Request, call_next):
    # Se seu provedor injeta X-Forwarded-Proto/For/Host, o HTTPSRedirect vai respeitar
    # (o Uvicorn/Starlette já entende Forwarded se a infra estiver correta)
    return await call_next(request)


# --- SESSÃO (necessário para request.session) ---
# Use uma chave forte em produção (ex.: variável de ambiente)
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "dev-change-me"))

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="sai_session",  # nome do cookie de sessão
    max_age=60 * 60 * 24 * 7,  # 7 dias
    same_site="lax",  # bom para navegação normal
    https_only=bool(
        os.getenv("SECURE_COOKIES", "false").lower() == "true"
    ),  # true em produção HTTPS
)

app.include_router(auth_router)
app.include_router(dashboard_student_router)
app.include_router(dashboard_professional_router)
app.include_router(dashboard_coordination_router)
app.include_router(ui_router)


# --- Endpoints
@app.get("/healthz", tags=["ops"])
def healthz():
    get_logger().info("health.check")
    return {"status": "ok", "env": settings.APP_ENV, "version": APP_VERSION}


@app.get("/version", tags=["ops"])
def version():
    return {
        "version": APP_VERSION,
        "git_sha": GIT_SHA,
        "build_time_utc": BUILD_TIME_UTC,
        "env": settings.APP_ENV,
        "debug": settings.DEBUG,
    }


@app.exception_handler(404)
async def not_found(_, __):
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.exception_handler(HTTPException)
async def ui_http_exception_handler(request, exc):
    path = request.url.path
    if path.startswith("/ui/") and exc.status_code in (401, 403):
        nxt = quote(str(request.url), safe="")
        return RedirectResponse(url=f"/ui/login?next={nxt}", status_code=303)
    return await http_exception_handler(request, exc)


@app.get("/")
def home_redirect(
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
):
    if not current_user:
        return RedirectResponse("/ui/login", status_code=303)
    # mesmo roteamento da after-login
    if current_user.role == Role.STUDENT:
        return RedirectResponse("/ui/student/appointments", status_code=303)
    if current_user.role == Role.PROFESSIONAL:
        return RedirectResponse("/ui/professional/week", status_code=303)
    if current_user.role == Role.COORDINATION:
        return RedirectResponse("/ui/coordination/overview", status_code=303)
    return RedirectResponse("/ui/login", status_code=303)
