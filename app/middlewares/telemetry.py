from __future__ import annotations
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger, set_request_id, request_id_ctx, user_id_ctx

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1) request-id: usa X-Request-ID se vier, ou gera
        incoming = request.headers.get("X-Request-ID")
        rid = set_request_id(incoming)

        # 2) (opcional) extraia user_id do auth se tiver (ex: request.state.user.id)
        # user_id = getattr(getattr(request.state, "user", None), "id", None)
        # if user_id: user_id_ctx.set(str(user_id))

        # 3) log de entrada
        log = get_logger().bind(request_id=rid, path=request.url.path, method=request.method)
        log.info("request.start")

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # loga erro com traceback já em JSON
            log.exception("request.error")
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0

        # 4) inclui cabeçalho de correlação na resposta
        response.headers["X-Request-ID"] = rid

        # 5) log de saída (access log com status + duração)
        log.bind(status_code=response.status_code, duration_ms=round(duration_ms, 2)).info("request.end")
        return response
