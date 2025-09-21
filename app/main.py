from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse

import app.db.base
from app.db import get_db
from app.api.main import api_router
from app.api.test_router import test_router
from app.core.logging import configure_logging, get_logger
from app.core.security import CSPMiddleware
from app.core.settings import settings
from app.deps import get_current_user
from app.middlewares.telemetry import RequestContextMiddleware
from app.models.user import Role, User
from app.version import APP_VERSION, BUILD_TIME_UTC, GIT_SHA
from app.web.routes import auth, coordination, family, professional, student
from app.api.v1 import public_appointments
from app.web.templating import templates

configure_logging(json=True, level="INFO")

app = FastAPI(debug=settings.DEBUG)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.state.templates = templates
# templates = Jinja2Templates(directory="app/web/templates")
# templates.env.auto_reload = True
# templates.env.cache = {}
# templates.env.globals["app_version"] = str(int(time.time()))

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
app.add_middleware(CSPMiddleware)


# Include public appointments router directly (no versioning)
app.include_router(public_appointments.router)

# Include the new API router with version prefix
app.include_router(api_router)

# Include test router
app.include_router(test_router)

# Keep existing web UI routers
app.include_router(family.router)
app.include_router(professional.router)
app.include_router(coordination.router)
app.include_router(student.router)
app.include_router(auth.router)


@app.get("/test-public")
def test_public():
    return {"message": "Public route working!"}


@app.get("/test-db")
def test_db(db: Session = Depends(get_db)):
    # Try to query a simple table to see if DB is working
    from app.models.appointment_token import AppointmentToken
    count = db.query(AppointmentToken).count()
    return {"message": "DB working", "token_count": count}


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


@app.get("/")
def home_redirect(
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
):
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    # mesmo roteamento da after-login (páginas não-UI)
    if current_user.role == Role.FAMILY:
        return RedirectResponse("/family/dashboard", status_code=303)
    if current_user.role == Role.PROFESSIONAL:
        return RedirectResponse("/professional/dashboard", status_code=303)
    if current_user.role == Role.COORDINATION:
        return RedirectResponse("/coordination/dashboard", status_code=303)
    if current_user.role == Role.STUDENT:
        return RedirectResponse("/student/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)
