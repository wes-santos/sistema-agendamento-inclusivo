from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.responses import JSONResponse

from app.api.routes.auth import router as auth_router
from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.middlewares.telemetry import RequestContextMiddleware
from app.version import APP_VERSION, BUILD_TIME_UTC, GIT_SHA

configure_logging(json=True, level="INFO")

app = FastAPI(debug=settings.DEBUG)

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


app.include_router(auth_router)


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
