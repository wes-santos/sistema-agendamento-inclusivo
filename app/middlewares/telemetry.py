from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger, set_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get("X-Request-ID")
        rid = set_request_id(incoming)

        log = get_logger().bind(
            request_id=rid, path=request.url.path, method=request.method
        )
        log.info("request.start")

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.exception("request.error: %s", exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0

        response.headers["X-Request-ID"] = rid

        log.bind(
            status_code=response.status_code, duration_ms=round(duration_ms, 2)
        ).info("request.end")
        return response
