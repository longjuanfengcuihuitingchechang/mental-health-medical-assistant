from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class UserRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ASSISTANT = "assistant"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class DirectoryTarget(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ASSISTANT = "assistant"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"
    PENDING = "pending"


class EmploymentStatus(StrEnum):
    ACTIVE = "active"
    LEAVE = "leave"
    RESIGNED = "resigned"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class AdminDirectoryRequest:
    target_role: DirectoryTarget
    keyword: str | None = None
    account_status: AccountStatus | None = None
    blacklisted: bool | None = None
    employment_status: EmploymentStatus | None = None
    limit: int = 50
    offset: int = 0

    def validated(self) -> "AdminDirectoryRequest":
        keyword = self.keyword.strip() if self.keyword else None
        if keyword and len(keyword) > 100:
            raise ValueError("keyword 长度不能超过 100")
        if not 1 <= self.limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        if self.offset < 0:
            raise ValueError("offset 不能小于 0")
        if (
            self.employment_status is not None
            and self.target_role not in {DirectoryTarget.DOCTOR, DirectoryTarget.ASSISTANT}
        ):
            raise ValueError("employment_status 仅适用于医生或助理目录")
        return AdminDirectoryRequest(
            target_role=self.target_role,
            keyword=keyword,
            account_status=self.account_status,
            blacklisted=self.blacklisted,
            employment_status=self.employment_status,
            limit=self.limit,
            offset=self.offset,
        )


@dataclass(frozen=True, slots=True)
class AdminDirectoryResponse:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class DirectoryPermissionError(PermissionError):
    """Raised when an authenticated subject cannot query a directory."""
