"""Correlation IDs, security headers, request-size limits and per-tenant CORS for public routes."""

from __future__ import annotations

import logging
import re
import secrets
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.tenancy import public

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("trustdesk.http")

_PUBLIC = re.compile(r"^/v1/public/(td_pk_[A-Za-z0-9_-]{8,58})/")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.match(incoming) else secrets.token_hex(8)
        request_id_var.set(rid)
        request.state.request_id = rid

        settings = get_settings()
        length = request.headers.get("content-length")
        limit = settings.max_upload_bytes if request.url.path.endswith("/upload") else settings.max_request_bytes
        if length and length.isdigit() and int(length) > limit:
            return self._finish(JSONResponse({"error": "request too large", "request_id": rid}, 413), rid)

        cors_origin: str | None = None
        match = _PUBLIC.match(request.url.path)
        if match:
            origin = request.headers.get("origin")
            tenant = await public.resolve(match.group(1))
            if tenant is None:
                return self._finish(JSONResponse({"error": "unknown assistant", "request_id": rid}, 404), rid)
            normalized = public.normalize_origin(origin) if origin else None
            if origin is not None and (normalized is None or normalized not in tenant.allowed_origins):
                log.info("blocked origin request_id=%s tenant=%s", rid, tenant.tenant_id)
                return self._finish(JSONResponse({"error": "origin not allowed", "request_id": rid}, 403), rid)
            if origin is None and settings.is_production and request.method != "GET":
                return self._finish(JSONResponse({"error": "origin required", "request_id": rid}, 403), rid)
            request.state.public_tenant = tenant
            cors_origin = origin
            if request.method == "OPTIONS":
                resp = Response(status_code=204)
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "content-type, x-request-id, last-event-id"
                resp.headers["Access-Control-Max-Age"] = "600"
                return self._finish(resp, rid, cors_origin)

        response = await call_next(request)
        return self._finish(response, rid, cors_origin)

    @staticmethod
    def _finish(response: Response, rid: str, cors_origin: str | None = None) -> Response:
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if cors_origin:
            response.headers["Access-Control-Allow-Origin"] = cors_origin
            response.headers["Access-Control-Expose-Headers"] = "x-request-id"
            response.headers["Vary"] = "Origin"
        return response
