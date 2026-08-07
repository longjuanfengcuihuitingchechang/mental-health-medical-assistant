from __future__ import annotations

from app.schemas.registration import (
    DoctorApprovalRequest,
    DoctorApprovalResponse,
    RegistrationRequest,
    RegistrationResponse,
)
from app.services.registration_service import (
    DoctorRegistrationApprovalService,
    RegistrationService,
)


class RegistrationAgent:
    """Deterministic patient and doctor registration agent."""

    def __init__(self, service: RegistrationService):
        self.service = service

    def run(self, request: RegistrationRequest) -> RegistrationResponse:
        return self.service.register(request)


class DoctorRegistrationApprovalAgent:
    """Admin-only deterministic doctor registration review agent."""

    def __init__(self, service: DoctorRegistrationApprovalService):
        self.service = service

    def run(
        self,
        *,
        requester_user_id: str,
        request: DoctorApprovalRequest,
    ) -> DoctorApprovalResponse:
        return self.service.review(
            requester_user_id=requester_user_id,
            request=request,
        )

    def list_requests(self, *, requester_user_id: str, status: str = "pending", limit: int = 50, offset: int = 0) -> dict:
        return self.service.list_requests(requester_user_id=requester_user_id, status=status, limit=limit, offset=offset)
