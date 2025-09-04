from __future__ import annotations

import contextvars
import logging
import sys
import uuid

import structlog

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
user_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)


def get_logger() -> structlog.BoundLogger:
    return structlog.get_logger()


def configure_logging(json: bool = True, level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO), stream=sys.stdout
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def set_request_id(req_id: str | None) -> str:
    rid = req_id or str(uuid.uuid4())
    request_id_ctx.set(rid)
    return rid


def set_user_id(user_id: str | None) -> None:
    if user_id:
        user_id_ctx.set(user_id)
