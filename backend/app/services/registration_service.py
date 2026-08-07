from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.core.identifiers import IdentifierProtector
from app.core.passwords import PasswordHasher
from app.repositories.registration_repository import RegistrationRepository
from app.schemas.registration import (
    ApprovalAction,
    DoctorApprovalRequest,
    DoctorApprovalResponse,
    RegistrationPermissionError,
    RegistrationRequest,
    RegistrationResponse,
    RegistrationRole,
    RegistrationStatus,
)


class RegistrationService:
    def __init__(
        self,
        repository: RegistrationRepository,
        password_hasher: PasswordHasher,
        identifier_protector: IdentifierProtector,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.password_hasher = password_hasher
        self.identifier_protector = identifier_protector
        self.clock = clock or (lambda: datetime.now(UTC))

    def register(self, request: RegistrationRequest) -> RegistrationResponse:
        validated = self._validate_request(request)
        id_card = self.identifier_protector.parse_id_card(validated.id_card)
        phone = self.identifier_protector.normalize_phone(validated.phone)
        email = self.identifier_protector.normalize_email(validated.email)
        result = self.repository.create_registration(
            request=validated,
            password_hash=self.password_hasher.hash_password(validated.password),
            id_card_fingerprint=self.identifier_protector.fingerprint(
                "id_card", id_card.normalized
            ),
            id_card_masked=self.identifier_protector.mask(
                "id_card", id_card.normalized
            ),
            phone_fingerprint=self.identifier_protector.fingerprint("phone", phone),
            phone_masked=self.identifier_protector.mask("phone", phone),
            email_fingerprint=self.identifier_protector.fingerprint("email", email),
            email_masked=self.identifier_protector.mask("email", email),
            birth_date=id_card.birth_date.isoformat(),
            gender=id_card.gender,
            created_at=self._now(),
        )

        if validated.role is RegistrationRole.PATIENT:
            return RegistrationResponse(
                success=True,
                message="患者注册成功，可以登录。",
                account=result["account"],
                status=RegistrationStatus.ACTIVE,
            )
        return RegistrationResponse(
            success=True,
            message="医生注册申请已提交，管理员审批通过后方可登录。",
            account=result["account"],
            status=RegistrationStatus.PENDING_APPROVAL,
            registration_request_id=result["registration_request_id"],
        )

    @staticmethod
    def _validate_request(request: RegistrationRequest) -> RegistrationRequest:
        display_name = request.display_name.strip()
        if not 2 <= len(display_name) <= 50:
            raise ValueError("姓名长度必须在 2 到 50 之间")
        if not 12 <= len(request.password) <= 128:
            raise ValueError("密码长度必须在 12 到 128 之间")
        department = request.department.strip() if request.department else None
        title = (
            request.professional_title.strip()
            if request.professional_title
            else None
        )
        if request.role is RegistrationRole.DOCTOR and not department:
            raise ValueError("医生注册必须填写科室")
        if department and len(department) > 100:
            raise ValueError("科室长度不能超过 100")
        if title and len(title) > 100:
            raise ValueError("职称长度不能超过 100")
        return RegistrationRequest(
            role=request.role,
            password=request.password,
            display_name=display_name,
            id_card=request.id_card,
            phone=request.phone,
            email=request.email,
            department=department,
            professional_title=title,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class DoctorRegistrationApprovalService:
    def __init__(
        self,
        repository: RegistrationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(UTC))

    def review(
        self,
        *,
        requester_user_id: str,
        request: DoctorApprovalRequest,
    ) -> DoctorApprovalResponse:
        requester = self.repository.get_requester(requester_user_id)
        if (
            not requester
            or requester["role"] not in {"admin", "super_admin"}
            or requester["account_status"] != "active"
        ):
            raise RegistrationPermissionError("仅有效管理员可审批医生注册")
        if not request.registration_request_id.strip():
            raise ValueError("registration_request_id 不能为空")
        note = request.review_note.strip() if request.review_note else None
        if request.action is ApprovalAction.REJECT and not note:
            raise ValueError("拒绝医生注册时必须填写原因")
        if note and len(note) > 500:
            raise ValueError("审批备注不能超过 500 字")

        result = self.repository.review_doctor_registration(
            requester_user_id=requester_user_id,
            registration_request_id=request.registration_request_id,
            action=request.action,
            review_note=note,
            reviewed_at=self._now(),
        )
        status = (
            RegistrationStatus.APPROVED
            if result["status"] == "approved"
            else RegistrationStatus.REJECTED
        )
        return DoctorApprovalResponse(
            success=True,
            message="医生注册已批准" if status is RegistrationStatus.APPROVED else "医生注册已拒绝",
            account=result["account"],
            status=status,
        )

    def list_requests(self, *, requester_user_id: str, status: str = "pending", limit: int = 50, offset: int = 0) -> dict:
        requester = self.repository.get_requester(requester_user_id)
        if not requester or requester["role"] not in {"admin", "super_admin"} or requester["account_status"] != "active":
            raise RegistrationPermissionError("仅有效管理员可查看医生注册")
        if status not in {"pending", "approved", "rejected"} or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("注册申请查询参数不合法")
        items, total = self.repository.list_doctor_registrations(status, limit, offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
