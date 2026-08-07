from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.schemas.admin_directory import UserRole


class IdentityType(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ASSISTANT = "assistant"
    ADMIN = "admin"


class LoginErrorCode(StrEnum):
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    LOCK_WARNING = "LOCK_WARNING"
    TEMPORARILY_LOCKED = "TEMPORARILY_LOCKED"
    VALIDATION_ERROR = "VALIDATION_ERROR"


@dataclass(frozen=True, slots=True)
class LoginRequest:
    identity_type: IdentityType
    account: str
    password: str

    def validated(self) -> "LoginRequest":
        account = self.account.strip()
        if not 1 <= len(account) <= 100:
            raise ValueError("账号长度必须在 1 到 100 之间")
        if not 1 <= len(self.password) <= 1024:
            raise ValueError("密码长度必须在 1 到 1024 之间")
        return LoginRequest(
            identity_type=self.identity_type,
            account=account,
            password=self.password,
        )


@dataclass(frozen=True, slots=True)
class LoginResponse:
    success: bool
    message: str
    error_code: LoginErrorCode | None = None
    role: UserRole | None = None
    display_name: str | None = None
    redirect_path: str | None = None
    session_token: str | None = None
    csrf_token: str | None = None
    user_id: str | None = None
    account: str | None = None
    expires_at: str | None = None
    remaining_attempts: int | None = None
    locked_remaining_seconds: int | None = None
    must_change_password: bool = False
