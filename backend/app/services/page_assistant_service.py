from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Callable

from app.llm.base import BaseLLM, LLMMessage
from app.prompts.page_templates import (
    FEATURE_CAPABILITIES,
    INTRO_TEMPLATES,
    PAGE_GUIDE,
    build_page_system_prompt,
)
from app.repositories.page_assistant_repository import PageAssistantRepository
from app.schemas.page_assistant import (
    AgeGroup,
    AssistantHistoryMessage,
    AssistantHistoryResponse,
    AssistantResponseType,
    DoctorAvailability,
    DoctorOption,
    PageAssistantRequest,
    PageAssistantResponse,
    PatientAssistantPermissionError,
    PatientPage,
)
from app.schemas.async_tasks import TaskCancelledError, TaskTimedOutError

PAGE_KEYWORDS = {
    PatientPage.OVERVIEW: ("概览", "趋势", "最近筛查", "待办"),
    PatientPage.SUPPORT: ("智能支持", "对话", "助手", "隐私"),
    PatientPage.ASSESSMENTS: ("测评", "量表", "题目", "分数"),
    PatientPage.WELLBEING: ("日记", "情绪记录", "压力", "睡眠"),
    PatientPage.RESOURCES: ("随访", "资源", "热线", "同意"),
    PatientPage.CARE: ("诊疗", "医生", "就诊", "排队", "休假"),
}

CARE_WORDS = ("正式诊疗", "我要就诊", "看医生", "找医生", "心理医生", "预约医生")
CRISIS_WORDS = ("自杀", "自残", "不想活", "伤害自己", "伤害别人", "立即危险")


class PatientPageAssistantService:
    def __init__(
        self,
        repository: PageAssistantRepository,
        llm: BaseLLM,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.llm = llm
        self.clock = clock or (lambda: datetime.now(UTC))

    def respond(
        self,
        *,
        patient_user_id: str,
        request: PageAssistantRequest,
        on_delta: Callable[[str], None] | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> PageAssistantResponse:
        request = request.validated()
        patient = self._authorized_patient(patient_user_id)
        if request.feature_key not in FEATURE_CAPABILITIES[request.page]:
            raise ValueError("feature_key 不属于当前页面")
        now = self.clock()
        now_text = now.isoformat()
        age_group = self._age_group(patient["birth_date"], now.date())
        message = request.message
        try:
            session_id = self.repository.ensure_session(
                patient_user_id=patient_user_id,
                session_id=request.session_id,
                page=request.page.value,
                now=now_text,
            )
        except PermissionError as error:
            raise PatientAssistantPermissionError(str(error)) from error
        usage_count, introduction_shown = self.repository.record_usage_event(
            patient_user_id=patient_user_id,
            session_id=session_id,
            page=request.page.value,
            feature_key=request.feature_key,
            event_type=request.event.value,
            now=now_text,
        )

        def finish(**kwargs) -> PageAssistantResponse:
            response = PageAssistantResponse(
                session_id=session_id,
                feature_key=request.feature_key,
                usage_count=usage_count,
                **kwargs,
            )
            if message:
                self.repository.append_message_pair(
                    session_id=session_id,
                    page=request.page.value,
                    feature_key=request.feature_key,
                    user_content=message,
                    assistant_content=response.answer,
                    now=now_text,
                )
            return response

        if request.event.value in ("page_open", "feature_open"):
            if not introduction_shown:
                return finish(
                    response_type=AssistantResponseType.INTRODUCTION_SUPPRESSED,
                    page=request.page,
                    answer="",
                    age_group=age_group,
                    introduction_suppressed=True,
                )
            return finish(
                response_type=AssistantResponseType.PAGE_INTRO,
                page=request.page,
                answer=INTRO_TEMPLATES[(request.page, request.feature_key)],
                age_group=age_group,
            )

        if any(word in message for word in CRISIS_WORDS):
            return finish(
                response_type=AssistantResponseType.CRISIS_SUPPORT,
                page=request.page,
                answer=(
                    "我很重视你现在的安全。如果你或他人正处于立即危险中，请先联系"
                    "身边可信任的人，并立即拨打 110 或 120；你也可以拨打 12356 "
                    "全国统一心理援助热线。这个助手不会声称已经替你联系了医生或急救。"
                ),
                age_group=age_group,
                crisis_contacts=["12356", "110", "120"],
            )

        if request.page is PatientPage.CARE or any(word in message for word in CARE_WORDS):
            doctors = self._doctor_options(patient_user_id)
            guardian_needed = (
                age_group is AgeGroup.CHILD
                and patient["guardian_consent_status"] != "granted"
            )
            prefix = self._respectful_prefix(patient["display_name"], age_group)
            guardian_note = (
                " 由于你未满18周岁，正式诊疗前还需要按机构规则完成监护人支持或授权。"
                if guardian_needed
                else ""
            )
            return finish(
                response_type=AssistantResponseType.CARE_NAVIGATION,
                page=request.page,
                answer=(
                    f"{prefix}我已带你进入患者诊疗导航。下面只展示数据库中的真实状态；"
                    "原接诊医生会优先显示，请选择一位医生。"
                    f"{guardian_note}"
                ),
                age_group=age_group,
                suggested_page=PatientPage.CARE,
                doctors=doctors,
                requires_guardian_support=guardian_needed,
            )

        other_page = self._detect_other_page(message, request.page)
        if other_page:
            title = PAGE_GUIDE[other_page][0]
            return finish(
                response_type=AssistantResponseType.OUT_OF_SCOPE,
                page=request.page,
                answer=f"这个问题属于“{title}”页面。我可以带你前往该页面后再继续说明。",
                age_group=age_group,
                suggested_page=other_page,
            )

        system = build_page_system_prompt(
            request.page,
            request.feature_key,
            age_group,
        )
        history = self.repository.list_recent_messages(
            patient_user_id=patient_user_id,
            session_id=session_id,
            limit=12,
        )
        messages = (
            [LLMMessage("system", system)]
            + [LLMMessage(item["role"], item["content"]) for item in history]
            + [LLMMessage("user", message)]
        )
        try:
            if on_delta and callable(getattr(self.llm, "stream", None)):
                parts: list[str] = []
                length = 0
                for chunk in self.llm.stream(messages):
                    if should_stop:
                        should_stop()
                    text = str(chunk)[: max(0, 1_000 - length)]
                    if not text:
                        break
                    parts.append(text)
                    length += len(text)
                    on_delta(text)
                answer = "".join(parts).strip()
            else:
                answer = self.llm.generate(messages).strip()
                if on_delta and answer:
                    if should_stop:
                        should_stop()
                    on_delta(answer[:1_000])
        except (TaskCancelledError, TaskTimedOutError):
            raise
        except Exception:
            if on_delta:
                raise
            answer = "当前智能回答暂不可用，但本页其他功能不受影响。你可以稍后重试。"
        if not answer:
            answer = "我可以继续说明当前页面的功能和操作方法。"
        answer = answer[:1_000]
        return finish(
            response_type=AssistantResponseType.PAGE_ANSWER,
            page=request.page,
            answer=answer,
            age_group=age_group,
        )

    def history(
        self,
        *,
        patient_user_id: str,
        session_id: str,
        limit: int = 50,
    ) -> AssistantHistoryResponse:
        self._authorized_patient(patient_user_id)
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        if not self.repository.session_belongs_to_patient(
            patient_user_id=patient_user_id,
            session_id=session_id,
        ):
            raise PatientAssistantPermissionError("助手会话不存在或不属于当前患者")
        rows = self.repository.list_recent_messages(
            patient_user_id=patient_user_id,
            session_id=session_id,
            limit=limit,
        )
        return AssistantHistoryResponse(
            session_id=session_id,
            messages=[AssistantHistoryMessage(**row) for row in rows],
        )

    def _authorized_patient(self, patient_user_id: str) -> dict:
        patient = self.repository.get_patient(patient_user_id)
        if (
            not patient
            or patient["role"] != "patient"
            or patient["account_status"] != "active"
            or patient["blacklisted"]
        ):
            raise PatientAssistantPermissionError("仅可用的患者账号能够使用页面助手")
        if not patient["birth_date"]:
            raise ValueError("患者出生日期缺失，无法确定适龄交互方式")
        return patient

    def _doctor_options(self, patient_user_id: str) -> list[DoctorOption]:
        now = self.clock()
        options = []
        labels = {
            DoctorAvailability.WORKING: "工作中",
            DoctorAvailability.OFF_DUTY: "当前不在岗",
            DoctorAvailability.ON_LEAVE: "休假中",
            DoctorAvailability.UNAVAILABLE: "暂不可接诊",
            DoctorAvailability.UNKNOWN: "状态待确认",
        }
        for row in self.repository.list_doctor_options(patient_user_id):
            availability = DoctorAvailability(row["availability_status"])
            expected = row["expected_available_at"]
            remaining = None
            if availability is DoctorAvailability.ON_LEAVE and expected:
                available_at = datetime.fromisoformat(expected.replace("Z", "+00:00"))
                if available_at.tzinfo is None:
                    available_at = available_at.replace(tzinfo=UTC)
                remaining = max(0, math.ceil((available_at - now).total_seconds() / 86_400))
            options.append(
                DoctorOption(
                    doctor_user_id=row["doctor_user_id"],
                    display_name=row["display_name"],
                    department=row["department"],
                    professional_title=row["professional_title"],
                    availability=availability,
                    availability_label=labels[availability],
                    queue_length=int(row["queue_length"]),
                    patient_queue_position=row["queue_position"],
                    is_previous_doctor=row["last_visit_at"] is not None,
                    last_visit_at=row["last_visit_at"],
                    expected_available_at=expected,
                    leave_remaining_days=remaining,
                )
            )
        return options

    @staticmethod
    def _age_group(birth_date: str, today: date) -> AgeGroup:
        born = date.fromisoformat(birth_date)
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if age < 18:
            return AgeGroup.CHILD
        if age >= 65:
            return AgeGroup.OLDER_ADULT
        return AgeGroup.ADULT

    @staticmethod
    def _respectful_prefix(display_name: str, age_group: AgeGroup) -> str:
        if age_group is AgeGroup.CHILD:
            return f"{display_name}，谢谢你认真说明自己的需要。"
        if age_group is AgeGroup.OLDER_ADULT:
            return f"{display_name}，您好。"
        return f"{display_name}，您好。"

    @staticmethod
    def _detect_other_page(message: str, current: PatientPage) -> PatientPage | None:
        for page, keywords in PAGE_KEYWORDS.items():
            if page is not current and any(keyword in message for keyword in keywords):
                return page
        return None
