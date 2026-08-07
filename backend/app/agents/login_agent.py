from __future__ import annotations

from app.schemas.login import LoginRequest, LoginResponse
from app.services.login_service import LoginService


class LoginAgent:
    """Deterministic authentication agent; it does not call an LLM."""

    def __init__(self, service: LoginService):
        self.service = service

    def run(self, request: LoginRequest) -> LoginResponse:
        return self.service.login(request)
