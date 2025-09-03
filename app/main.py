from fastapi import FastAPI

from app.core.settings import settings

app = FastAPI(debug=settings.DEBUG)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": settings.APP_ENV}
