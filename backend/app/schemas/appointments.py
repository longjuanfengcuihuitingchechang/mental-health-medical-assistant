from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AppointmentStatus(StrEnum):
    QUEUED = "queued"
    AWAITING_PATIENT_DECISION = "awaiting_patient_decision"
    CHANGE_REQUESTED = "change_requested"
    AWAITING_DOCTOR_DECISION = "awaiting_doctor_decision"
    QUEUED_OVER_CAPACITY = "queued_over_capacity"
    DECLINED_DIRECT = "declined_direct"
    DECLINED_GENTLE = "declined_gentle"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PatientAppointmentDecision(StrEnum):
    SWITCH_DOCTOR = "switch_doctor"
    CONTINUE_REQUEST = "continue_request"


class DoctorAppointmentDecision(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"


class CommunicationMode(StrEnum):
    DIRECT = "direct"
    GENTLE = "gentle"


@dataclass(frozen=True, slots=True)
class CapacityRequest:
    appointment_date: str
    capacity: int


@dataclass(frozen=True, slots=True)
class CapacityResponse:
    doctor_user_id: str
    appointment_date: str
    capacity: int
    appointment_count: int
    version: int


@dataclass(frozen=True, slots=True)
class CreateAppointmentRequest:
    doctor_user_id: str
    appointment_date: str


@dataclass(frozen=True, slots=True)
class AppointmentResponse:
    appointment_id: str
    patient_user_id: str
    doctor_user_id: str
    appointment_date: str
    status: AppointmentStatus
    completed_visit_count: int
    capacity: int | None
    appointment_count: int
    queue_position: int
    message: str


@dataclass(frozen=True, slots=True)
class PatientDecisionRequest:
    appointment_id: str
    decision: PatientAppointmentDecision


@dataclass(frozen=True, slots=True)
class DoctorDecisionRequest:
    appointment_id: str
    decision: DoctorAppointmentDecision
    communication_mode: CommunicationMode | None = None


@dataclass(frozen=True, slots=True)
class AppointmentDecisionResponse:
    appointment_id: str
    status: AppointmentStatus
    patient_message: str


@dataclass(frozen=True, slots=True)
class NightShiftRequest:
    shift_date: str
    doctor_user_id: str


@dataclass(frozen=True, slots=True)
class NightShiftResponse:
    shift_date: str
    doctor_user_id: str
    doctor_display_name: str
    assigned_by_user_id: str


@dataclass(frozen=True, slots=True)
class PendingAppointment:
    appointment_id: str
    patient_user_id: str
    patient_display_name: str
    doctor_user_id: str
    doctor_display_name: str
    appointment_date: str
    queue_position: int
    status: AppointmentStatus


class AppointmentPermissionError(PermissionError):
    pass


class AppointmentEligibilityError(ValueError):
    pass


class AppointmentConflictError(RuntimeError):
    pass
