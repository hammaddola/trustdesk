"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from trustdesk_ai.api import admin_auth, admin_data, admin_playground, admin_settings, admin_sources, handoff, public
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.session import global_session
from trustdesk_ai.observability.middleware import RequestContextMiddleware, request_id_var

log = logging.getLogger("trustdesk")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request lines may contain query strings


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast with a clear message if configuration is invalid
    configure_logging()
    app = FastAPI(
        title="TrustDesk API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    for r in (
        public.router,
        handoff.router,
        admin_auth.router,
        admin_sources.router,
        admin_data.router,
        admin_settings.router,
        admin_playground.router,
    ):
        app.include_router(r)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail, "request_id": request_id_var.get()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only — never echo submitted values back.
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": "invalid request", "fields": errors, "request_id": request_id_var.get()}, 422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal error", "request_id": request_id_var.get()}, status_code=500)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        try:
            async with global_session() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            log.exception("readiness check failed")
            return JSONResponse({"status": "database unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app
