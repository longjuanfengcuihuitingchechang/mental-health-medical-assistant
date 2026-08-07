from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.core.identifiers import IdentifierProtector
from app.core.passwords import PasswordHasher
from app.repositories.login_repository import LoginRepository
from app.schemas.admin_directory import AccountStatus, UserRole
from app.schemas.login import (
    LoginErrorCode,
    LoginRequest,
    LoginResponse,
)


REDIRECT_PATHS = {
    UserRole.PATIENT: "patient/index.html",
    UserRole.DOCTOR: "doctor/index.html",
    UserRole.ASSISTANT: "assistant/index.html",
    UserRole.ADMIN: "admin/index.html",
    UserRole.SUPER_ADMIN: "admin/index.html",
}


class LoginService:
    def __init__(
        self,
        repository: LoginRepository,
        password_hasher: PasswordHasher,
        identifier_protector: IdentifierProtector | None = None,
        *,
        max_attempts: int = 8,
        lock_duration: timedelta = timedelta(minutes=5),
        session_duration: timedelta = timedelta(hours=8),
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.password_hasher = password_hasher
        self.identifier_protector = identifier_protector
        self.max_attempts = max_attempts
        self.lock_duration = lock_duration
        self.session_duration = session_duration
        self.clock = clock or (lambda: datetime.now(UTC))
        self._dummy_password_hash = password_hasher.hash_password(
            "dummy-password-used-only-for-timing-equalization"
        )

    def login(self, request: LoginRequest) -> LoginResponse:
        validated = request.validated()
        now = self._aware_utc(self.clock())
        fingerprint = self._login_fingerprint(validated)
        state = self.repository.get_security_state(fingerprint)

        if state and state["locked_until"]:
            locked_until = self._parse_datetime(state["locked_until"])
            if locked_until > now:
                remaining = max(1, int((locked_until - now).total_seconds() + 0.999))
                self.repository.write_audit(
                    actor_user_id=None,
                    account_fingerprint=fingerprint,
                    identity_type=validated.identity_type,
                    status="denied",
                    error_code=LoginErrorCode.TEMPORARILY_LOCKED.value,
                )
                return LoginResponse(
                    success=False,
                    message=f"登录失败次数过多，请在 {remaining} 秒后重试。",
                    error_code=LoginErrorCode.TEMPORARILY_LOCKED,
                    locked_remaining_seconds=remaining,
                )
            self.repository.reset_security_state(fingerprint)

        user = self.repository.find_user(
            identity_type=validated.identity_type,
            account=validated.account,
            identifier_fingerprint=fingerprint,
        )
        encoded_hash = user["password_hash"] if user else self._dummy_password_hash
        password_valid = self.password_hasher.verify_password(
            validated.password,
            encoded_hash,
        )
        account_active = bool(
            user and user["account_status"] == AccountStatus.ACTIVE.value
        )

        if not user or not password_valid or not account_active:
            return self._handle_failure(
                request=validated,
                fingerprint=fingerprint,
                user_id=user["id"] if user else None,
                now=now,
            )

        role = UserRole(user["role"])
        raw_token = secrets.token_urlsafe(32)
        raw_csrf_token = secrets.token_urlsafe(32)
        session_id = str(uuid.uuid4())
        expires_at = now + self.session_duration
        self.repository.create_session(
            session_id=session_id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            csrf_token_hash=hashlib.sha256(
                raw_csrf_token.encode("utf-8")
            ).hexdigest(),
            user_id=user["id"],
            created_at=now,
            expires_at=expires_at,
            account_fingerprint=fingerprint,
        )
        self.repository.write_audit(
            actor_user_id=user["id"],
            account_fingerprint=fingerprint,
            identity_type=validated.identity_type,
            status="success",
            error_code=None,
        )
        return LoginResponse(
            success=True,
            message="登录成功",
            role=role,
            display_name=user["display_name"],
            redirect_path=REDIRECT_PATHS[role],
            session_token=raw_token,
            csrf_token=raw_csrf_token,
            user_id=user["id"],
            account=user["account"],
            expires_at=expires_at.isoformat(),
            must_change_password=bool(user["must_change_password"]),
        )

    def _handle_failure(
        self,
        *,
        request: LoginRequest,
        fingerprint: str,
        user_id: str | None,
        now: datetime,
    ) -> LoginResponse:
        attempts, locked_until = self.repository.register_failure(
            account_fingerprint=fingerprint,
            user_id=user_id,
            failed_at=now,
            max_attempts=self.max_attempts,
            locked_until=now + self.lock_duration,
        )
        if locked_until:
            seconds = int(self.lock_duration.total_seconds())
            error_code = LoginErrorCode.TEMPORARILY_LOCKED
            message = "连续登录失败 8 次，账号已锁定 5 分钟。"
            remaining_attempts = 0
        elif attempts == self.max_attempts - 1:
            seconds = None
            error_code = LoginErrorCode.LOCK_WARNING
            message = "账号、密码或身份类型不匹配；再失败 1 次将锁定 5 分钟。"
            remaining_attempts = 1
        else:
            seconds = None
            error_code = LoginErrorCode.INVALID_CREDENTIALS
            message = "账号、密码或身份类型不匹配。"
            remaining_attempts = None

        self.repository.write_audit(
            actor_user_id=user_id,
            account_fingerprint=fingerprint,
            identity_type=request.identity_type,
            status="denied",
            error_code=error_code.value,
        )
        return LoginResponse(
            success=False,
            message=message,
            error_code=error_code,
            remaining_attempts=remaining_attempts,
            locked_remaining_seconds=seconds,
        )

    def _login_fingerprint(self, request: LoginRequest) -> str:
        if self.identifier_protector:
            try:
                kind = self.identifier_protector.detect_login_kind(request.account)
                return self.identifier_protector.fingerprint(kind, request.account)
            except ValueError:
                pass
        material = f"{request.identity_type.value}\0{request.account.casefold()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return LoginService._aware_utc(datetime.fromisoformat(value))

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
