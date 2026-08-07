from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from app.llm.base import BaseLLM, LLMMessage
from app.repositories.appointment_repository import AppointmentRepository
from app.schemas.appointments import (
    AppointmentConflictError,
    AppointmentDecisionResponse,
    AppointmentEligibilityError,
    AppointmentPermissionError,
    AppointmentResponse,
    AppointmentStatus,
    CapacityRequest,
    CapacityResponse,
    CommunicationMode,
    CreateAppointmentRequest,
    DoctorAppointmentDecision,
    DoctorDecisionRequest,
    NightShiftRequest,
    NightShiftResponse,
    PatientAppointmentDecision,
    PatientDecisionRequest,
    PendingAppointment,
)


class AppointmentService:
    def __init__(
        self,
        repository: AppointmentRepository,
        llm: BaseLLM,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.llm = llm
        self.clock = clock or (lambda: datetime.now(UTC))

    def set_capacity(
        self,
        *,
        doctor_user_id: str,
        request: CapacityRequest,
    ) -> CapacityResponse:
        self._require_role(doctor_user_id, {"doctor"})
        target = self._next_two_day(request.appointment_date)
        if not 0 <= request.capacity <= 1000:
            raise ValueError("capacity 必须在 0 到 1000 之间")
        row = self.repository.set_capacity(
            doctor_user_id=doctor_user_id,
            appointment_date=target.isoformat(),
            capacity=request.capacity,
            now=self.clock().isoformat(),
        )
        return CapacityResponse(
            doctor_user_id=doctor_user_id,
            appointment_date=target.isoformat(),
            capacity=row["capacity"],
            appointment_count=row["count"],
            version=row["version"],
        )

    def summary(self, *, requester_user_id: str, doctor_user_id: str, appointment_date: str) -> dict:
        self._require_role(requester_user_id, {"patient", "doctor", "assistant", "admin", "super_admin"})
        target = date.fromisoformat(appointment_date)
        row = self.repository.appointment_summary(doctor_user_id, target.isoformat())
        return row

    def get_night_shift(self, *, requester_user_id: str, shift_date: str) -> dict:
        self._require_role(requester_user_id, {"patient", "doctor", "assistant", "admin", "super_admin"})
        target = date.fromisoformat(shift_date)
        row = self.repository.get_night_shift(target.isoformat())
        return {"shift_date": target.isoformat(), "item": row}

    def create(
        self,
        *,
        patient_user_id: str,
        request: CreateAppointmentRequest,
    ) -> AppointmentResponse:
        self._require_role(patient_user_id, {"patient"})
        self._require_role(request.doctor_user_id, {"doctor"})
        target = self._next_two_day(request.appointment_date)
        visits = self.repository.completed_visit_count(patient_user_id)
        if visits < 10:
            raise AppointmentEligibilityError(
                f"累计完成就诊 {visits} 次，达到 10 次后才能指定医生预约"
            )
        try:
            row = self.repository.create_appointment(
                patient_user_id=patient_user_id,
                doctor_user_id=request.doctor_user_id,
                appointment_date=target.isoformat(),
                now=self.clock().isoformat(),
            )
        except RuntimeError as error:
            raise AppointmentConflictError(str(error)) from error
        status = AppointmentStatus(row["status"])
        if status is AppointmentStatus.QUEUED:
            message = "预约已进入队列，请留意队列位置变化。"
        else:
            message = (
                "该医生当前预约人数已达到或超过计划容量。"
                "你愿意更换医生吗？如果仍希望预约这位医生，我会把请求交给医生确认。"
            )
        return AppointmentResponse(
            appointment_id=row["id"],
            patient_user_id=patient_user_id,
            doctor_user_id=request.doctor_user_id,
            appointment_date=target.isoformat(),
            status=status,
            completed_visit_count=visits,
            capacity=row["capacity"],
            appointment_count=row["appointment_count"],
            queue_position=row["queue_number"],
            message=message,
        )

    def patient_decide(
        self,
        *,
        patient_user_id: str,
        request: PatientDecisionRequest,
    ) -> AppointmentDecisionResponse:
        self._require_role(patient_user_id, {"patient"})
        try:
            status = self.repository.patient_decide(
                patient_user_id=patient_user_id,
                appointment_id=request.appointment_id,
                decision=request.decision.value,
                now=self.clock().isoformat(),
            )
        except PermissionError as error:
            raise AppointmentPermissionError(str(error)) from error
        message = (
            "已返回医生选择，请选择其他医生。"
            if request.decision is PatientAppointmentDecision.SWITCH_DOCTOR
            else "已将超额预约请求提交给医生，请等待医生确认。"
        )
        return AppointmentDecisionResponse(
            appointment_id=request.appointment_id,
            status=AppointmentStatus(status),
            patient_message=message,
        )

    def doctor_decide(
        self,
        *,
        doctor_user_id: str,
        request: DoctorDecisionRequest,
    ) -> AppointmentDecisionResponse:
        self._require_role(doctor_user_id, {"doctor"})
        if request.decision is DoctorAppointmentDecision.DECLINE:
            if request.communication_mode is None:
                raise ValueError("拒绝接诊时必须选择 direct 或 gentle")
            message = self._decline_message(request.communication_mode)
        else:
            if request.communication_mode is not None:
                raise ValueError("接受接诊时不能设置拒绝告知方式")
            message = "医生已接受你的超额预约请求。你仍需按当前队列顺序等待。"
        try:
            status = self.repository.doctor_decide(
                doctor_user_id=doctor_user_id,
                appointment_id=request.appointment_id,
                decision=request.decision.value,
                communication_mode=(
                    request.communication_mode.value
                    if request.communication_mode
                    else None
                ),
                patient_message=message,
                now=self.clock().isoformat(),
            )
        except PermissionError as error:
            raise AppointmentPermissionError(str(error)) from error
        return AppointmentDecisionResponse(
            appointment_id=request.appointment_id,
            status=AppointmentStatus(status),
            patient_message=message,
        )

    def pending(self, *, requester_user_id: str) -> list[PendingAppointment]:
        user = self._require_role(
            requester_user_id,
            {"doctor", "assistant", "admin", "super_admin"},
        )
        rows = self.repository.list_pending_decisions(
            doctor_user_id=requester_user_id if user["role"] == "doctor" else None
        )
        return [
            PendingAppointment(
                **{**row, "status": AppointmentStatus(row["status"])}
            )
            for row in rows
        ]

    def assign_night_shift(
        self,
        *,
        requester_user_id: str,
        request: NightShiftRequest,
    ) -> NightShiftResponse:
        self._require_role(requester_user_id, {"assistant", "admin", "super_admin"})
        self._require_role(request.doctor_user_id, {"doctor"})
        shift_date = date.fromisoformat(request.shift_date)
        if shift_date < self.clock().date():
            raise ValueError("不能安排过去日期的夜班")
        try:
            row = self.repository.assign_night_shift(
                shift_date=shift_date.isoformat(),
                doctor_user_id=request.doctor_user_id,
                assigned_by_user_id=requester_user_id,
                now=self.clock().isoformat(),
            )
        except RuntimeError as error:
            raise AppointmentConflictError(str(error)) from error
        return NightShiftResponse(
            shift_date=shift_date.isoformat(),
            doctor_user_id=request.doctor_user_id,
            doctor_display_name=row["display_name"],
            assigned_by_user_id=requester_user_id,
        )

    def _require_role(self, user_id: str, roles: set[str]) -> dict:
        user = self.repository.get_user(user_id)
        if (
            not user
            or user["role"] not in roles
            or user["account_status"] != "active"
            or user["blacklisted"]
        ):
            raise AppointmentPermissionError("账号无权执行该预约操作")
        if user["role"] == "doctor" and user["doctor_employment_status"] != "active":
            raise AppointmentPermissionError("医生当前不在职，不能处理预约")
        if user["role"] == "assistant" and user["assistant_employment_status"] != "active":
            raise AppointmentPermissionError("助理当前不在职，不能处理协调任务")
        return user

    def _next_two_day(self, value: str) -> date:
        target = date.fromisoformat(value)
        today = self.clock().date()
        if target not in {today + timedelta(days=1), today + timedelta(days=2)}:
            raise ValueError("预约日期只能是服务端日期后的第 1 或第 2 天")
        return target

    def _decline_message(self, mode: CommunicationMode) -> str:
        direct = "医生未接受本次超额预约。你可以返回医生列表选择其他医生。"
        if mode is CommunicationMode.DIRECT:
            return direct
        try:
            answer = self.llm.generate(
                [
                    LLMMessage(
                        "system",
                        "把预约拒绝通知改写为尊重、委婉、不责备患者的中文，"
                        "不超过80字；不得编造原因、诊断、名额或替代医生承诺。",
                    ),
                    LLMMessage("user", direct),
                ]
            ).strip()
            return answer[:300] or "很抱歉，医生目前无法接受这次超额预约。你可以选择其他医生，我们会继续协助。"
        except Exception:
            return "很抱歉，医生目前无法接受这次超额预约。你可以选择其他医生，我们会继续协助。"
