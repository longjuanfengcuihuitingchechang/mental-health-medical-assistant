from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RegistrationRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"


class RegistrationStatus(StrEnum):
    ACTIVE = "active"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RegistrationRequest:
    role: RegistrationRole
    password: str
    display_name: str
    id_card: str
    phone: str
    email: str
    department: str | None = None
    professional_title: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationResponse:
    success: bool
    message: str
    account: str | None = None
    status: RegistrationStatus | None = None
    registration_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorApprovalRequest:
    registration_request_id: str
    action: ApprovalAction
    review_note: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorApprovalResponse:
    success: bool
    message: str
    account: str
    status: RegistrationStatus


class RegistrationConflictError(ValueError):
    """A unique personal or login identifier is already registered."""


class RegistrationPermissionError(PermissionError):
    """The authenticated subject cannot review doctor registrations."""


class RegistrationStateError(ValueError):
    """The registration request is missing or no longer pending."""
