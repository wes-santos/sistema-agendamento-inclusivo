from fastapi import FastAPI
from app.core.settings import settings
from app.core.logging import configure_logging, get_logger
from app.middlewares.telemetry import RequestContextMiddleware

configure_logging(json=True, level="INFO")
app = FastAPI(debug=settings.DEBUG)

app.add_middleware(RequestContextMiddleware)


@app.get("/healthz")
def healthz():
    get_logger().info("health.check")
    return {"status": "ok", "env": settings.APP_ENV}

