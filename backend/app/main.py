from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router
from app.api.security_middleware import RequestBodyLimitMiddleware
from app.container import build_application_agents
from app.core.config import Settings, settings
from app.core.errors import APIError
from app.db.connection import SQLiteConnectionFactory
from app.repositories.runtime_repository import RuntimeRepository
from app.repositories.security_repository import SecurityRepository
from app.services.security_service import SecurityService
from app.core.security_logging import configure_security_logging


def create_app(app_settings: Settings = settings) -> FastAPI:
    app_settings.validate_security()
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        if application.state.async_task_service is not None:
            application.state.async_task_service.close()

    app = FastAPI(
        title="Mental Health Medical Assistant",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if app_settings.app_env == "production" else "/docs",
        redoc_url=None if app_settings.app_env == "production" else "/redoc",
        openapi_url=None if app_settings.app_env == "production" else "/openapi.json",
    )
    app.state.settings = app_settings
    app.state.logger = logging.getLogger("mental_health_assistant")
    configure_security_logging(app.state.logger)
    app.state.connection_factory = SQLiteConnectionFactory(
        app_settings.validated_database_path()
    )
    app.state.runtime_repository = RuntimeRepository(app.state.connection_factory)
    app.state.security_service = None
    app.state.agents = None
    app.state.async_task_service = None
    app.state.agents_factory = lambda: build_application_agents(app_settings)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.monotonic()
        if app.state.security_service is None:
            app.state.security_service = SecurityService(
                SecurityRepository(app.state.connection_factory),
                app_settings.load_auth_pepper(),
            )
        request.state.request_id = f"req_{uuid.uuid4().hex}"
        client_host = request.client.host if request.client else "unknown"
        request.state.ip_fingerprint = app.state.security_service.fingerprint("ip", client_host)
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
        configured_origins = set(app_settings.cors_allowed_origins())
        if origin and origin.rstrip("/") != same_origin and origin.rstrip("/") not in configured_origins:
            app.state.security_service.audit(
                action="security.origin_denied",
                target_type="http_request",
                status="denied",
                request_id=request.state.request_id,
                ip_fingerprint=request.state.ip_fingerprint,
                error_code="ORIGIN_DENIED",
                metadata={"method": request.method, "path_template": "origin_check"},
            )
            return JSONResponse(
                status_code=403,
                content={
                    "code": 40304,
                    "message": "请求来源不被允许",
                    "data": {"error": "ORIGIN_DENIED"},
                    "request_id": request.state.request_id,
                },
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        if app_settings.app_env == "production":
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.tailwindcss.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if app_settings.session_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        route = request.scope.get("route")
        path_template = getattr(route, "path", "unmatched")
        app.state.logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s latency_ms=%s",
            request.state.request_id,
            request.method,
            path_template,
            response.status_code,
            int((time.monotonic() - started) * 1000),
        )
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        if exc.status_code in {403, 429}:
            session = getattr(request.state, "session", None)
            try:
                app.state.security_service.audit(
                    action="security.request_denied",
                    target_type="http_request",
                    status="denied",
                    actor_user_id=session.get("user_id") if session else None,
                    request_id=request.state.request_id,
                    ip_fingerprint=getattr(request.state, "ip_fingerprint", None),
                    error_code=exc.error,
                    metadata={
                        "role": session.get("role") if session else None,
                        "method": request.method,
                        "path_template": getattr(request.scope.get("route"), "path", request.url.path),
                        "status_code": exc.status_code,
                    },
                )
            except Exception as audit_error:
                app.state.logger.error(
                    "security_audit_failed request_id=%s error=%s",
                    request.state.request_id,
                    type(audit_error).__name__,
                )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "data": {"error": exc.error, **exc.data},
                "request_id": request.state.request_id,
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content={
                "code": 40001,
                "message": "请求参数不合法",
                "data": {"error": "VALIDATION_ERROR", "fields": fields},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(PermissionError)
    async def permission_handler(request: Request, exc: PermissionError):
        session = getattr(request.state, "session", None)
        try:
            app.state.security_service.audit(
                action="security.scope_denied",
                target_type="domain_resource",
                status="denied",
                actor_user_id=session.get("user_id") if session else None,
                request_id=request.state.request_id,
                ip_fingerprint=getattr(request.state, "ip_fingerprint", None),
                error_code="PERMISSION_DENIED",
                metadata={"role": session.get("role") if session else None},
            )
        except Exception:
            pass
        return JSONResponse(status_code=403, content={"code": 40301, "message": str(exc), "data": {"error": "PERMISSION_DENIED"}, "request_id": request.state.request_id})

    @app.exception_handler(ValueError)
    async def value_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"code": 40001, "message": str(exc), "data": {"error": "VALIDATION_ERROR"}, "request_id": request.state.request_id})

    @app.exception_handler(RuntimeError)
    async def conflict_handler(request: Request, exc: RuntimeError):
        return JSONResponse(status_code=409, content={"code": 40901, "message": str(exc), "data": {"error": "CONFLICT"}, "request_id": request.state.request_id})

    app.include_router(router)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=app_settings.max_request_body_bytes,
    )
    allowed_origins = list(app_settings.cors_allowed_origins())
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token", "Last-Event-ID"],
        )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(app_settings.allowed_hosts()),
    )
    static_path = app_settings.static_files_path
    if static_path.is_dir():
        app.mount("/", StaticFiles(directory=static_path, html=True), name="fronts")
    return app


app = create_app()
