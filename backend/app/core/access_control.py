from __future__ import annotations

from enum import StrEnum

from app.core.errors import APIError


class Permission(StrEnum):
    PATIENT_SELF = "patient:self"
    DOCTOR_SELF = "doctor:self"
    ASSISTANT_COORDINATION = "assistant:coordination"
    DIRECTORY_READ = "directory:read"
    DOCTOR_APPROVAL = "doctor_registration:approve"
    NIGHT_SHIFT_MANAGE = "night_shift:manage"
    TASK_SELF = "task:self"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "patient": frozenset({Permission.PATIENT_SELF, Permission.TASK_SELF}),
    "doctor": frozenset({Permission.DOCTOR_SELF, Permission.TASK_SELF}),
    "assistant": frozenset({
        Permission.ASSISTANT_COORDINATION,
        Permission.NIGHT_SHIFT_MANAGE,
        Permission.TASK_SELF,
    }),
    "admin": frozenset({
        Permission.DIRECTORY_READ,
        Permission.DOCTOR_APPROVAL,
        Permission.NIGHT_SHIFT_MANAGE,
        Permission.TASK_SELF,
    }),
    "super_admin": frozenset({
        Permission.DIRECTORY_READ,
        Permission.DOCTOR_APPROVAL,
        Permission.NIGHT_SHIFT_MANAGE,
        Permission.TASK_SELF,
    }),
}


def require_permission(session: dict, permission: Permission) -> None:
    if permission not in ROLE_PERMISSIONS.get(session.get("role", ""), frozenset()):
        raise APIError(403, 40301, "PERMISSION_DENIED", "当前角色无权执行该操作")
