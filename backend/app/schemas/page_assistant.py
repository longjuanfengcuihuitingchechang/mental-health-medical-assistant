from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PatientPage(StrEnum):
    OVERVIEW = "overview"
    SUPPORT = "support"
    ASSESSMENTS = "assessments"
    WELLBEING = "wellbeing"
    RESOURCES = "resources"
    CARE = "care"


class AssistantResponseType(StrEnum):
    PAGE_INTRO = "page_intro"
    PAGE_ANSWER = "page_answer"
    OUT_OF_SCOPE = "out_of_scope"
    CARE_NAVIGATION = "care_navigation"
    CRISIS_SUPPORT = "crisis_support"
    INTRODUCTION_SUPPRESSED = "introduction_suppressed"


class AssistantEvent(StrEnum):
    PAGE_OPEN = "page_open"
    FEATURE_OPEN = "feature_open"
    MESSAGE = "message"


class AgeGroup(StrEnum):
    CHILD = "child"
    ADULT = "adult"
    OLDER_ADULT = "older_adult"


class DoctorAvailability(StrEnum):
    WORKING = "working"
    OFF_DUTY = "off_duty"
    ON_LEAVE = "on_leave"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PageAssistantRequest:
    page: PatientPage
    message: str = ""
    session_id: str | None = None
    feature_key: str = "page"
    event: AssistantEvent | None = None

    def validated(self) -> "PageAssistantRequest":
        message = self.message.strip()
        if len(message) > 2_000:
            raise ValueError("message 长度不能超过 2000")
        session_id = self.session_id.strip() if self.session_id else None
        if session_id and len(session_id) > 100:
            raise ValueError("session_id 长度不能超过 100")
        feature_key = self.feature_key.strip()
        if not feature_key or len(feature_key) > 64:
            raise ValueError("feature_key 不合法")
        event = self.event or (
            AssistantEvent.MESSAGE if message else AssistantEvent.PAGE_OPEN
        )
        if event is AssistantEvent.MESSAGE and not message:
            raise ValueError("message 事件必须包含消息")
        if event is not AssistantEvent.MESSAGE and message:
            raise ValueError("打开事件不能包含消息")
        return PageAssistantRequest(
            page=self.page,
            message=message,
            session_id=session_id,
            feature_key=feature_key,
            event=event,
        )


@dataclass(frozen=True, slots=True)
class DoctorOption:
    doctor_user_id: str
    display_name: str
    department: str | None
    professional_title: str | None
    availability: DoctorAvailability
    availability_label: str
    queue_length: int
    patient_queue_position: int | None
    is_previous_doctor: bool
    last_visit_at: str | None
    expected_available_at: str | None
    leave_remaining_days: int | None


@dataclass(frozen=True, slots=True)
class PageAssistantResponse:
    response_type: AssistantResponseType
    page: PatientPage
    answer: str
    age_group: AgeGroup
    suggested_page: PatientPage | None = None
    doctors: list[DoctorOption] = field(default_factory=list)
    requires_guardian_support: bool = False
    crisis_contacts: list[str] = field(default_factory=list)
    session_id: str = ""
    feature_key: str = "page"
    usage_count: int = 0
    introduction_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class AssistantHistoryMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class AssistantHistoryResponse:
    session_id: str
    messages: list[AssistantHistoryMessage] = field(default_factory=list)


class PatientAssistantPermissionError(PermissionError):
    pass
