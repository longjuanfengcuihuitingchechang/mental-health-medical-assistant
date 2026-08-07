from __future__ import annotations

from app.schemas.admin_directory import (
    AdminDirectoryRequest,
    AdminDirectoryResponse,
)
from app.services.admin_directory_service import AdminDirectoryService


class AdminDirectoryAgent:
    """A deterministic, read-only directory agent.

    The requester_user_id must come from an authenticated server-side session.
    It must never be accepted as trusted identity directly from browser JSON.
    """

    def __init__(self, service: AdminDirectoryService):
        self.service = service

    def run(
        self,
        *,
        requester_user_id: str,
        request: AdminDirectoryRequest,
    ) -> AdminDirectoryResponse:
        return self.service.list_people(
            requester_user_id=requester_user_id,
            request=request,
        )
