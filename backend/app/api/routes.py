from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_agents,
    get_async_task_service,
    get_current_session,
    require_csrf,
)
from app.api.models import (
    AppointmentBody, ApprovalBody, CapacityBody, DoctorDecisionBody,
    LoginBody, NightShiftBody, PageAssistantBody, PatientDecisionBody,
    RegistrationBody, WorkAssistantBody,
)
from app.core.errors import APIError
from app.schemas.login import IdentityType, LoginErrorCode, LoginRequest
from app.schemas.admin_directory import AccountStatus, AdminDirectoryRequest, DirectoryTarget, EmploymentStatus
from app.schemas.appointments import (
    CapacityRequest, CommunicationMode, CreateAppointmentRequest,
    DoctorAppointmentDecision, DoctorDecisionRequest, NightShiftRequest,
    PatientAppointmentDecision, PatientDecisionRequest,
)
from app.schemas.page_assistant import AssistantEvent, PageAssistantRequest, PatientPage
from app.schemas.registration import ApprovalAction, DoctorApprovalRequest, RegistrationRequest, RegistrationRole
from app.schemas.work_assistant import WorkAssistantRequest
from app.schemas.async_tasks import TaskNotFoundError, TaskStatus
from app.core.access_control import Permission, require_permission


router = APIRouter(prefix="/api/v1")


def success(request: Request, data=None, message: str = "success") -> dict:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": request.state.request_id,
    }


def protect_write(session: dict, csrf: str | None) -> None:
    require_csrf(session, csrf)


def require_role(session: dict, *roles: str) -> None:
    if session["role"] not in roles:
        raise APIError(403, 40301, "PERMISSION_DENIED", "当前角色无权执行该操作")


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> None:
    result = request.app.state.security_service.consume(
        scope=scope,
        subject=subject,
        limit=limit,
        window_seconds=window_seconds,
    )
    if result.allowed:
        return
    error = APIError(429, 42901, "RATE_LIMITED", "请求过于频繁，请稍后重试")
    error.data = {"retry_after": result.retry_after}
    error.headers = {"Retry-After": str(result.retry_after)}
    raise error


def audit_action(
    request: Request,
    session: dict | None,
    *,
    action: str,
    target_type: str,
    resource_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    request.app.state.security_service.audit(
        action=action,
        target_type=target_type,
        status="success",
        actor_user_id=session.get("user_id") if session else None,
        resource_id=resource_id,
        request_id=request.state.request_id,
        ip_fingerprint=request.state.ip_fingerprint,
        metadata=metadata,
    )


@router.get("/health/live")
def live(request: Request) -> dict:
    return success(request, {"status": "alive", "version": "1.0.0"})


@router.get("/health/ready")
def ready(request: Request) -> dict:
    try:
        version = request.app.state.runtime_repository.readiness()
        if int(version) < 9:
            raise RuntimeError("schema version is below 9")
    except Exception as exc:
        request.app.state.logger.warning(
            "readiness_failed request_id=%s error=%s",
            request.state.request_id,
            type(exc).__name__,
        )
        raise APIError(503, 50303, "DEPENDENCY_NOT_READY", "数据库尚未就绪")
    return success(request, {"status": "ready", "schema_version": int(version)})


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, agents=Depends(get_agents)):
    limits = request.app.state.settings
    enforce_rate_limit(
        request,
        scope="login_ip",
        subject=request.state.ip_fingerprint,
        limit=limits.login_ip_limit,
        window_seconds=limits.login_rate_window_seconds,
    )
    enforce_rate_limit(
        request,
        scope="login_account",
        subject=f"{body.identity_type}:{body.account.casefold()}",
        limit=limits.login_account_limit,
        window_seconds=limits.login_rate_window_seconds,
    )
    result = agents.login.run(
        LoginRequest(
            identity_type=IdentityType(body.identity_type),
            account=body.account,
            password=body.password,
        )
    )
    if not result.success:
        request.app.state.security_service.audit(
            action="security.login_failed",
            target_type="session",
            status="denied",
            request_id=request.state.request_id,
            ip_fingerprint=request.state.ip_fingerprint,
            error_code=result.error_code.value,
            metadata={"identity_type": body.identity_type},
        )
        if result.error_code is LoginErrorCode.TEMPORARILY_LOCKED:
            raise APIError(423, 42301, "LOGIN_TEMPORARILY_LOCKED", result.message)
        data = {
            "remaining_attempts": result.remaining_attempts,
            "warning": "ONE_ATTEMPT_REMAINING"
            if result.error_code is LoginErrorCode.LOCK_WARNING
            else None,
        }
        error = APIError(401, 40102, "INVALID_CREDENTIALS", result.message)
        error.data = data
        raise error
    response.set_cookie(
        "mh_session",
        result.session_token,
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=request.app.state.settings.session_hours * 3600,
    )
    data = asdict(result)
    data.pop("session_token", None)
    data.pop("success", None)
    data.pop("error_code", None)
    audit_action(
        request,
        {"user_id": result.user_id, "role": result.role.value},
        action="security.login_succeeded",
        target_type="session",
        metadata={"role": result.role.value, "identity_type": body.identity_type},
    )
    return success(request, data, result.message)


@router.get("/auth/session")
def current_session(request: Request, session=Depends(get_current_session)) -> dict:
    csrf_token = secrets.token_urlsafe(32)
    csrf_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()
    request.app.state.runtime_repository.rotate_csrf(session["session_id"], csrf_hash)
    return success(
        request,
        {
            "user_id": session["user_id"],
            "account": session["account"],
            "role": session["role"],
            "display_name": session["display_name"],
            "expires_at": session["expires_at"],
            "must_change_password": bool(session["must_change_password"]),
            "csrf_token": csrf_token,
        },
    )


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    session=Depends(get_current_session),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    require_csrf(session, x_csrf_token)
    request.app.state.runtime_repository.revoke_session(session["session_id"])
    response.delete_cookie("mh_session", path="/")
    return success(request)


@router.post("/registrations")
def register(body: RegistrationBody, request: Request, agents=Depends(get_agents)):
    payload = body.model_dump()
    payload["role"] = RegistrationRole(body.role)
    result = agents.registration.run(RegistrationRequest(**payload))
    return success(request, asdict(result), result.message)


@router.post("/admin/doctor-registrations/{registration_request_id}/decision")
def approve_doctor(registration_request_id: str, body: ApprovalBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.DOCTOR_APPROVAL)
    result = agents.doctor_registration_approval.run(requester_user_id=session["user_id"], request=DoctorApprovalRequest(registration_request_id, ApprovalAction(body.action), body.review_note))
    audit_action(request, session, action="admin.doctor_registration_decided", target_type="doctor_registration", resource_id=registration_request_id, metadata={"role": session["role"]})
    return success(request, asdict(result), result.message)


@router.get("/admin/doctor-registrations")
def list_doctor_registrations(request: Request, status: str = "pending", limit: int = 50, offset: int = 0, session=Depends(get_current_session), agents=Depends(get_agents)):
    require_permission(session, Permission.DOCTOR_APPROVAL)
    result = agents.doctor_registration_approval.list_requests(requester_user_id=session["user_id"], status=status, limit=limit, offset=offset)
    return success(request, result)


@router.get("/admin/directory/{target_role}")
def directory(target_role: DirectoryTarget, request: Request, keyword: str | None = None, account_status: AccountStatus | None = None, blacklisted: bool | None = None, employment_status: EmploymentStatus | None = None, limit: int = 50, offset: int = 0, session=Depends(get_current_session), agents=Depends(get_agents)):
    require_permission(session, Permission.DIRECTORY_READ)
    result = agents.admin_directory.run(requester_user_id=session["user_id"], request=AdminDirectoryRequest(target_role, keyword, account_status, blacklisted, employment_status, limit, offset))
    audit_action(request, session, action="admin.directory_read", target_type=target_role.value, metadata={"role": session["role"], "result_count": result.total})
    return success(request, asdict(result))


@router.post("/patient/page-assistant/respond")
def patient_assistant(body: PageAssistantBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.PATIENT_SELF)
    settings = request.app.state.settings
    enforce_rate_limit(request, scope="assistant_user", subject=session["user_id"], limit=settings.assistant_user_limit, window_seconds=settings.assistant_rate_window_seconds)
    result = agents.patient_page_assistant.run(requester_user_id=session["user_id"], request=PageAssistantRequest(PatientPage(body.page), body.message, body.assistant_session_id, body.feature_key, AssistantEvent(body.event) if body.event else None))
    return success(request, asdict(result))


def task_payload(task) -> dict:
    data = asdict(task)
    data["stream_url"] = f"/api/v1/agent-tasks/{task.task_id}/events"
    data["cancel_url"] = f"/api/v1/agent-tasks/{task.task_id}/cancel"
    return data


@router.post("/patient/page-assistant/tasks", status_code=202)
def create_patient_assistant_task(
    body: PageAssistantBody,
    request: Request,
    response: Response,
    session=Depends(get_current_session),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    tasks=Depends(get_async_task_service),
):
    protect_write(session, csrf)
    require_permission(session, Permission.PATIENT_SELF)
    settings = request.app.state.settings
    enforce_rate_limit(request, scope="assistant_user", subject=session["user_id"], limit=settings.assistant_user_limit, window_seconds=settings.assistant_rate_window_seconds)
    result = tasks.create_patient_task(
        owner_user_id=session["user_id"],
        request=PageAssistantRequest(
            PatientPage(body.page),
            body.message,
            body.assistant_session_id,
            body.feature_key,
            AssistantEvent(body.event) if body.event else None,
        ),
    )
    if result.mode == "synchronous":
        response.status_code = 200
        return success(
            request,
            {"mode": result.mode, "crisis": result.crisis, "response": result.response},
        )
    data = {"mode": result.mode, **task_payload(result.task)}
    audit_action(request, session, action="agent.task_created", target_type="async_task", resource_id=result.task.task_id, metadata={"role": session["role"], "task_type": result.task.task_type.value})
    return success(request, data)


@router.get("/patient/page-assistant/sessions/{assistant_session_id}/messages")
def patient_history(assistant_session_id: str, request: Request, limit: int = 50, session=Depends(get_current_session), agents=Depends(get_agents)):
    require_permission(session, Permission.PATIENT_SELF)
    result = agents.patient_page_assistant.history(requester_user_id=session["user_id"], session_id=assistant_session_id, limit=limit)
    return success(request, asdict(result))


@router.put("/doctors/me/capacities/{appointment_date}")
def set_capacity(appointment_date: str, body: CapacityBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.DOCTOR_SELF)
    result = agents.appointment_capacity.run(requester_user_id=session["user_id"], request=CapacityRequest(appointment_date, body.capacity))
    return success(request, asdict(result))


@router.get("/doctors/{doctor_user_id}/appointment-summary")
def appointment_summary(doctor_user_id: str, appointment_date: str, request: Request, session=Depends(get_current_session), agents=Depends(get_agents)):
    result = agents.appointment_capacity.summary(requester_user_id=session["user_id"], doctor_user_id=doctor_user_id, appointment_date=appointment_date)
    return success(request, result)


@router.post("/patient/appointments")
def create_appointment(body: AppointmentBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.PATIENT_SELF)
    result = agents.patient_appointment.run(requester_user_id=session["user_id"], request=CreateAppointmentRequest(body.doctor_user_id, body.appointment_date))
    return success(request, asdict(result))


@router.post("/patient/appointments/{appointment_id}/decision")
def patient_decision(appointment_id: str, body: PatientDecisionBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.PATIENT_SELF)
    result = agents.patient_appointment.decide(requester_user_id=session["user_id"], request=PatientDecisionRequest(appointment_id, PatientAppointmentDecision(body.decision)))
    return success(request, asdict(result))


@router.get("/doctors/me/appointments/pending-decisions")
def doctor_pending(request: Request, session=Depends(get_current_session), agents=Depends(get_agents)):
    require_permission(session, Permission.DOCTOR_SELF)
    return success(request, [asdict(item) for item in agents.appointment_decision.pending(requester_user_id=session["user_id"])])


@router.get("/assistants/me/coordination-queue")
def assistant_pending(request: Request, session=Depends(get_current_session), agents=Depends(get_agents)):
    require_permission(session, Permission.ASSISTANT_COORDINATION)
    return success(request, [asdict(item) for item in agents.appointment_decision.pending(requester_user_id=session["user_id"])])


@router.post("/doctors/me/appointments/{appointment_id}/decision")
def doctor_decision(appointment_id: str, body: DoctorDecisionBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.DOCTOR_SELF)
    result = agents.appointment_decision.decide(requester_user_id=session["user_id"], request=DoctorDecisionRequest(appointment_id, DoctorAppointmentDecision(body.decision), CommunicationMode(body.communication_mode) if body.communication_mode else None))
    return success(request, asdict(result))


@router.put("/night-shifts/{shift_date}")
def assign_night_shift(shift_date: str, body: NightShiftBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    protect_write(session, csrf)
    require_permission(session, Permission.NIGHT_SHIFT_MANAGE)
    result = agents.night_shift.run(requester_user_id=session["user_id"], request=NightShiftRequest(shift_date, body.doctor_user_id))
    audit_action(request, session, action="admin.night_shift_assigned", target_type="night_shift", resource_id=f"{shift_date}:{body.doctor_user_id}", metadata={"role": session["role"]})
    return success(request, asdict(result))


@router.get("/night-shifts/{shift_date}")
def get_night_shift(shift_date: str, request: Request, session=Depends(get_current_session), agents=Depends(get_agents)):
    return success(request, agents.night_shift.get(requester_user_id=session["user_id"], shift_date=shift_date))


@router.post("/{role}/work-assistant/respond")
def work_assistant(role: str, body: WorkAssistantBody, request: Request, session=Depends(get_current_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), agents=Depends(get_agents)):
    if role not in {"doctor", "assistant"} or session["role"] != role:
        raise APIError(403, 40301, "PERMISSION_DENIED", "角色与工作助手不匹配")
    protect_write(session, csrf)
    require_permission(session, Permission.DOCTOR_SELF if role == "doctor" else Permission.ASSISTANT_COORDINATION)
    settings = request.app.state.settings
    enforce_rate_limit(request, scope="assistant_user", subject=session["user_id"], limit=settings.assistant_user_limit, window_seconds=settings.assistant_rate_window_seconds)
    result = agents.work_assistant.run(requester_user_id=session["user_id"], role=role, request=WorkAssistantRequest(body.page, body.feature_key, body.message, body.assistant_session_id))
    return success(request, asdict(result))


@router.post("/{role}/work-assistant/tasks", status_code=202)
def create_work_assistant_task(
    role: str,
    body: WorkAssistantBody,
    request: Request,
    session=Depends(get_current_session),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    tasks=Depends(get_async_task_service),
):
    if role not in {"doctor", "assistant"} or session["role"] != role:
        raise APIError(403, 40301, "PERMISSION_DENIED", "角色与工作助手不匹配")
    protect_write(session, csrf)
    require_permission(session, Permission.DOCTOR_SELF if role == "doctor" else Permission.ASSISTANT_COORDINATION)
    settings = request.app.state.settings
    enforce_rate_limit(request, scope="assistant_user", subject=session["user_id"], limit=settings.assistant_user_limit, window_seconds=settings.assistant_rate_window_seconds)
    result = tasks.create_work_task(
        owner_user_id=session["user_id"],
        role=role,
        request=WorkAssistantRequest(
            body.page,
            body.feature_key,
            body.message,
            body.assistant_session_id,
        ),
    )
    data = {"mode": result.mode, **task_payload(result.task)}
    audit_action(request, session, action="agent.task_created", target_type="async_task", resource_id=result.task.task_id, metadata={"role": session["role"], "task_type": result.task.task_type.value})
    return success(request, data)


@router.get("/agent-tasks/{task_id}")
def get_agent_task(
    task_id: str,
    request: Request,
    session=Depends(get_current_session),
    tasks=Depends(get_async_task_service),
):
    require_permission(session, Permission.TASK_SELF)
    try:
        task = tasks.get(session["user_id"], task_id)
    except TaskNotFoundError as error:
        raise APIError(404, 40401, "TASK_NOT_FOUND", str(error)) from error
    return success(request, task_payload(task))


@router.post("/agent-tasks/{task_id}/cancel")
def cancel_agent_task(
    task_id: str,
    request: Request,
    session=Depends(get_current_session),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    tasks=Depends(get_async_task_service),
):
    protect_write(session, csrf)
    require_permission(session, Permission.TASK_SELF)
    try:
        task = tasks.cancel(session["user_id"], task_id)
    except TaskNotFoundError as error:
        raise APIError(404, 40401, "TASK_NOT_FOUND", str(error)) from error
    audit_action(request, session, action="agent.task_cancel_requested", target_type="async_task", resource_id=task_id, metadata={"role": session["role"], "task_type": task.task_type.value})
    return success(request, task_payload(task))


@router.get("/agent-tasks/{task_id}/events")
async def stream_agent_task(
    task_id: str,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    session=Depends(get_current_session),
    tasks=Depends(get_async_task_service),
):
    require_permission(session, Permission.TASK_SELF)
    try:
        header_cursor = int(last_event_id or 0)
        cursor = max(after or 0, header_cursor)
    except ValueError as error:
        raise APIError(400, 40001, "INVALID_EVENT_ID", "Last-Event-ID 不合法") from error
    try:
        tasks.get(session["user_id"], task_id)
    except TaskNotFoundError as error:
        raise APIError(404, 40401, "TASK_NOT_FOUND", str(error)) from error

    async def event_stream():
        nonlocal cursor
        last_activity = asyncio.get_running_loop().time()
        while True:
            if await request.is_disconnected():
                return
            events = tasks.events(session["user_id"], task_id, after=cursor)
            for event in events:
                cursor = event.event_id
                payload = {
                    "event_id": event.event_id,
                    "task_id": event.task_id,
                    "created_at": event.created_at,
                    **event.data,
                }
                yield (
                    f"id: {event.event_id}\n"
                    f"event: {event.event_type.value}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                )
                last_activity = asyncio.get_running_loop().time()
            snapshot = tasks.get(session["user_id"], task_id)
            if snapshot.status.terminal and not events:
                return
            now = asyncio.get_running_loop().time()
            if now - last_activity >= 10:
                yield f"event: heartbeat\ndata: {json.dumps({'task_id': task_id}, ensure_ascii=False)}\n\n"
                last_activity = now
            await asyncio.sleep(0.15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
