from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity_type: Literal["patient", "doctor", "assistant", "admin"]
    account: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class Envelope(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
    request_id: str


class RegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["patient", "doctor"]
    password: str
    display_name: str
    id_card: str
    phone: str
    email: str
    department: str | None = None
    professional_title: str | None = None


class ApprovalBody(BaseModel):
    action: Literal["approve", "reject"]
    review_note: str | None = None


class PageAssistantBody(BaseModel):
    page: Literal["overview", "support", "assessments", "wellbeing", "resources", "care"]
    message: str = ""
    assistant_session_id: str | None = None
    feature_key: str = "page"
    event: Literal["page_open", "feature_open", "message"] | None = None


class CapacityBody(BaseModel):
    capacity: int = Field(ge=0, le=1000)


class AppointmentBody(BaseModel):
    doctor_user_id: str
    appointment_date: str


class PatientDecisionBody(BaseModel):
    decision: Literal["switch_doctor", "continue_request"]


class DoctorDecisionBody(BaseModel):
    decision: Literal["accept", "decline"]
    communication_mode: Literal["direct", "gentle"] | None = None


class NightShiftBody(BaseModel):
    doctor_user_id: str


class WorkAssistantBody(BaseModel):
    page: str = Field(min_length=1, max_length=64)
    feature_key: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    assistant_session_id: str | None = None
