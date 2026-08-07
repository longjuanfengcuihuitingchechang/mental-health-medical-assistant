from __future__ import annotations

from app.repositories.admin_directory_repository import AdminDirectoryRepository
from app.schemas.admin_directory import (
    AccountStatus,
    AdminDirectoryRequest,
    AdminDirectoryResponse,
    DirectoryPermissionError,
    DirectoryTarget,
    UserRole,
)


class AdminDirectoryService:
    def __init__(self, repository: AdminDirectoryRepository):
        self.repository = repository

    def list_people(
        self,
        *,
        requester_user_id: str,
        request: AdminDirectoryRequest,
    ) -> AdminDirectoryResponse:
        validated = request.validated()
        requester = self.repository.get_requester(requester_user_id)

        try:
            self._authorize(requester, validated.target_role)
            items, total = self.repository.list_directory(validated)
            self.repository.write_audit(
                requester_user_id=requester_user_id,
                request=validated,
                status="success",
                result_count=len(items),
            )
            return AdminDirectoryResponse(
                items=items,
                total=total,
                limit=validated.limit,
                offset=validated.offset,
            )
        except DirectoryPermissionError:
            self.repository.write_audit(
                requester_user_id=requester_user_id if requester else None,
                request=validated,
                status="denied",
                result_count=0,
                error_code="FORBIDDEN",
            )
            raise

    @staticmethod
    def _authorize(
        requester: dict | None,
        target_role: DirectoryTarget,
    ) -> None:
        if not requester:
            raise DirectoryPermissionError("请求者不存在")
        if requester["account_status"] != AccountStatus.ACTIVE.value:
            raise DirectoryPermissionError("请求者账号不可用")

        role = UserRole(requester["role"])
        if role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
            raise DirectoryPermissionError("仅管理员可使用人员目录 Agent")
        if target_role is DirectoryTarget.ADMIN and role is not UserRole.SUPER_ADMIN:
            raise DirectoryPermissionError("仅最高管理员可查看管理员基本信息")
