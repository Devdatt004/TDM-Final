"""
api/http_layer.py

Step 15 - cross-cutting HTTP contract for /api/v1.

* X-Request-ID      echoed (if a safe value was sent) or generated on every response.
* Deprecation       legacy unversioned aliases answer with Deprecation / Sunset /
                    Link: <successor>; rel="successor-version" headers.
* Error envelope    every error keeps FastAPI's ``detail`` (existing clients) and adds
                    ``error: {code, message, request_id}``. Unhandled exceptions become a
                    generic 500 - internals are logged, never returned.
* Idempotency-Key   optional on POST/PATCH under /api/v1. The first request with a key
                    claims it (unique per caller); a retry with the same key and body
                    replays the stored response (Idempotent-Replayed: true); a different
                    body, or a retry while the first is still running, is a 409.
                    Only 2xx responses are kept; keys expire after 24 hours.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from metadata_store.db import get_db
from metadata_store.models import IdempotencyRecord

logger = logging.getLogger("tdm.api")

API_PREFIX = "/api/v1"
SUNSET = "Wed, 30 Jun 2027 00:00:00 GMT"
UNVERSIONED_OK = ("/health", "/docs", "/redoc", "/openapi.json")
IDEMPOTENCY_TTL = timedelta(hours=24)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

ERROR_CODES = {
    400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 422: "validation_error",
    429: "rate_limited", 500: "internal_error", 503: "unavailable",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "-"


def _envelope(request: Request, status: int, detail, message: str = None) -> JSONResponse:
    if message is None:
        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, dict) and isinstance(detail.get("message"), str):
            message = detail["message"]
        else:
            message = ERROR_CODES.get(status, "error").replace("_", " ").capitalize() + "."
    body = {"detail": detail,
            "error": {"code": ERROR_CODES.get(status, "error"), "message": message,
                      "request_id": _request_id(request)}}
    # Set here too: the catch-all 500 handler runs outside the middleware stack.
    return JSONResponse(body, status_code=status, headers={"X-Request-ID": _request_id(request)})


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        response = _envelope(request, exc.status_code, exc.detail)
        for k, v in (exc.headers or {}).items():
            response.headers[k] = v
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
                  for e in exc.errors()]
        return _envelope(request, 422, errors, "The request is invalid.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error [request_id=%s]", _request_id(request))
        return _envelope(request, 500, "Internal server error.")

    app.add_middleware(IdempotencyMiddleware, app_ref=app)
    app.add_middleware(RequestContextMiddleware)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        path = request.url.path
        if not path.startswith(API_PREFIX) and not path.startswith(UNVERSIONED_OK) and request.method != "OPTIONS":
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = SUNSET
            response.headers["Link"] = f'<{API_PREFIX}{path}>; rel="successor-version"'
        return response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, app_ref: FastAPI):
        super().__init__(app)
        self.app_ref = app_ref

    def _session(self):
        """Same session source the routes use (honours test dependency overrides)."""
        factory = self.app_ref.dependency_overrides.get(get_db, get_db)
        gen = factory()
        return gen, next(gen)

    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("Idempotency-Key")
        if key is None or request.method not in ("POST", "PATCH") or not request.url.path.startswith(API_PREFIX):
            return await call_next(request)
        request.state.request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
        if not _SAFE_ID.match(key):
            return _envelope(request, 422, "Idempotency-Key must be 1-128 letters, digits or _.:-")

        body = await request.body()
        caller = request.headers.get("Authorization") or (
            request.headers.get("X-Dev-User", "") + "|" + request.headers.get("X-Dev-Roles", ""))
        scope = hashlib.sha256(caller.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            request.method.encode() + b" " + str(request.url.path).encode() + b"?" +
            str(request.url.query).encode() + b"\n" + body).hexdigest()

        gen, db = self._session()
        try:
            now = datetime.utcnow()
            db.query(IdempotencyRecord).filter(IdempotencyRecord.created_at < now - IDEMPOTENCY_TTL).delete()
            db.commit()
            record = db.query(IdempotencyRecord).filter_by(scope=scope, key=key).first()
            if record is not None:
                if record.fingerprint != fingerprint:
                    return _envelope(request, 409, "Idempotency-Key was already used for a different request.")
                if record.status_code is None:
                    return _envelope(request, 409, "A request with this Idempotency-Key is still in progress.")
                replay = Response(content=record.response_body, status_code=record.status_code,
                                  media_type="application/json")
                replay.headers["Idempotent-Replayed"] = "true"
                return replay
            record = IdempotencyRecord(scope=scope, key=key, fingerprint=fingerprint, created_at=now)
            db.add(record)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return _envelope(request, 409, "A request with this Idempotency-Key is still in progress.")

            try:
                response = await call_next(request)
            except Exception:
                db.delete(record)          # release the claim so the client can retry
                db.commit()
                raise
            chunks = [chunk async for chunk in response.body_iterator]
            content = b"".join(chunks)
            if 200 <= response.status_code < 300 and response.media_type in (None, "application/json") \
                    and "application/json" in response.headers.get("content-type", "application/json"):
                record.status_code = response.status_code
                record.response_body = content.decode("utf-8", errors="replace")
                db.commit()
            else:
                db.delete(record)          # failures may be retried with the same key
                db.commit()
            return Response(content=content, status_code=response.status_code,
                            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
                            media_type=response.media_type)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
