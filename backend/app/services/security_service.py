from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from app.repositories.security_repository import SecurityRepository


SAFE_METADATA_KEYS = {
    "role",
    "permission",
    "method",
    "path_template",
    "status_code",
    "limit",
    "window_seconds",
    "task_type",
    "identity_type",
    "result_count",
}


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after: int
    count: int


class SecurityService:
    def __init__(self, repository: SecurityRepository, secret: bytes):
        if len(secret) < 32:
            raise ValueError("安全指纹密钥长度不足")
        self.repository = repository
        self.secret = secret

    def fingerprint(self, purpose: str, value: str | None) -> str | None:
        if not value:
            return None
        material = f"{purpose}\0{value}".encode("utf-8")
        return hmac.new(self.secret, material, hashlib.sha256).hexdigest()

    def consume(
        self,
        *,
        scope: str,
        subject: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        bucket = self.fingerprint("rate", f"{scope}\0{subject}")
        allowed, retry, count = self.repository.consume_rate_limit(
            bucket_key=bucket,
            limit=limit,
            window_seconds=window_seconds,
            now=datetime.now(UTC),
        )
        return RateLimitResult(allowed, retry, count)

    def audit(
        self,
        *,
        action: str,
        target_type: str,
        status: str,
        actor_user_id: str | None = None,
        resource_id: str | None = None,
        request_id: str | None = None,
        ip_fingerprint: str | None = None,
        error_code: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        safe_metadata = {
            key: value
            for key, value in (metadata or {}).items()
            if key in SAFE_METADATA_KEYS
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        self.repository.append_audit(
            actor_user_id=actor_user_id,
            action=action[:100],
            target_type=target_type[:64],
            status=status,
            error_code=error_code[:100] if error_code else None,
            request_id=request_id,
            ip_fingerprint=ip_fingerprint,
            resource_fingerprint=self.fingerprint("resource", resource_id),
            metadata=safe_metadata,
        )
