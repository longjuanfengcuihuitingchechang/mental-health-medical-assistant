from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class TaskType(StrEnum):
    PATIENT_PAGE_ASSISTANT = "patient_page_assistant"
    DOCTOR_WORK_ASSISTANT = "doctor_work_assistant"
    ASSISTANT_WORK_ASSISTANT = "assistant_work_assistant"


class TaskEventType(StrEnum):
    CREATED = "task.created"
    STARTED = "task.started"
    DELTA = "message.delta"
    WAITING = "task.waiting"
    COMPLETED = "task.completed"
    FAILED = "task.failed"
    CANCELLED = "task.cancelled"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True, slots=True)
class TaskEvent:
    event_id: int
    task_id: str
    event_type: TaskEventType
    data: dict
    created_at: str


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    task_type: TaskType
    status: TaskStatus
    role: str
    output: dict | None
    error_code: str | None
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class TaskCreationResult:
    mode: str
    task: TaskSnapshot | None = None
    response: dict | None = None
    crisis: bool = False


class TaskNotFoundError(PermissionError):
    pass


class TaskCancelledError(RuntimeError):
    pass


class TaskTimedOutError(TimeoutError):
    pass
