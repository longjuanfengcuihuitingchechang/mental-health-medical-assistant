from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import Cookie, Header, Request

from app.core.errors import APIError
from app.repositories.async_task_repository import AsyncTaskRepository
from app.services.async_task_service import AsyncTaskService


def get_agents(request: Request):
    if request.app.state.agents is None:
        request.app.state.agents = request.app.state.agents_factory()
    return request.app.state.agents


def get_async_task_service(request: Request) -> AsyncTaskService:
    if request.app.state.async_task_service is None:
        request.app.state.async_task_service = AsyncTaskService(
            AsyncTaskRepository(request.app.state.connection_factory),
            get_agents(request),
            timeout_seconds=request.app.state.settings.agent_task_timeout_seconds,
            max_workers=request.app.state.settings.agent_task_workers,
        )
    return request.app.state.async_task_service


def get_current_session(
    request: Request,
    mh_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if not mh_session:
        raise APIError(401, 40101, "AUTH_REQUIRED", "登录状态无效或已过期")
    token_hash = hashlib.sha256(mh_session.encode("utf-8")).hexdigest()
    session = request.app.state.runtime_repository.get_session(token_hash)
    if not session:
        raise APIError(401, 40101, "AUTH_REQUIRED", "登录状态无效或已过期")
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        session["revoked_at"]
        or expires_at <= datetime.now(UTC)
        or session["account_status"] != "active"
    ):
        raise APIError(401, 40101, "AUTH_REQUIRED", "登录状态无效或已过期")
    request.state.session = session
    return session


def require_csrf(
    session: dict[str, Any],
    x_csrf_token: str | None = Header(default=None),
) -> None:
    expected = session.get("csrf_token_hash")
    actual = (
        hashlib.sha256(x_csrf_token.encode("utf-8")).hexdigest()
        if x_csrf_token
        else ""
    )
    if not expected or not hmac.compare_digest(expected, actual):
        raise APIError(403, 40303, "CSRF_FAILED", "请求安全校验失败")
