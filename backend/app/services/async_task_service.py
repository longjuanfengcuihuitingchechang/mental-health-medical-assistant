from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Lock

from app.repositories.async_task_repository import AsyncTaskRepository
from app.schemas.async_tasks import (
    TaskCancelledError,
    TaskCreationResult,
    TaskEvent,
    TaskSnapshot,
    TaskStatus,
    TaskTimedOutError,
    TaskType,
)
from app.schemas.page_assistant import PageAssistantRequest
from app.schemas.work_assistant import WorkAssistantRequest
from app.services.page_assistant_service import CRISIS_WORDS


class AsyncTaskService:
    """持久化任务状态；执行器可在 Linux 阶段替换为外部队列。"""

    def __init__(
        self,
        repository: AsyncTaskRepository,
        agents,
        *,
        timeout_seconds: float = 30.0,
        max_workers: int = 4,
    ):
        if timeout_seconds <= 0:
            raise ValueError("任务超时必须大于 0")
        if not 1 <= max_workers <= 32:
            raise ValueError("任务执行器数量必须在 1 到 32 之间")
        self.repository = repository
        self.agents = agents
        self.timeout_seconds = timeout_seconds
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-task",
        )
        self._closed = False
        self._close_lock = Lock()
        self.repository.fail_incomplete(
            "SERVICE_RESTARTED",
            "服务已重启，未完成内容未保存为成功结果",
        )

    def create_patient_task(
        self,
        *,
        owner_user_id: str,
        request: PageAssistantRequest,
    ) -> TaskCreationResult:
        request = request.validated()
        if any(word in request.message for word in CRISIS_WORDS):
            response = self.agents.patient_page_assistant.run(
                requester_user_id=owner_user_id,
                request=request,
            )
            return TaskCreationResult(
                mode="synchronous",
                response=asdict(response),
                crisis=True,
            )
        payload = {
            "page": request.page.value,
            "message": request.message,
            "assistant_session_id": request.session_id,
            "feature_key": request.feature_key,
            "event": request.event.value,
        }
        task = self.repository.create(
            owner_user_id=owner_user_id,
            role="patient",
            task_type=TaskType.PATIENT_PAGE_ASSISTANT,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            self._submit(task.task_id)
        except Exception:
            self.repository.fail(
                task.task_id,
                "TASK_QUEUE_FAILED",
                "任务未能进入执行队列",
            )
            raise
        return TaskCreationResult(mode="asynchronous", task=task)

    def create_work_task(
        self,
        *,
        owner_user_id: str,
        role: str,
        request: WorkAssistantRequest,
    ) -> TaskCreationResult:
        if role not in {"doctor", "assistant"}:
            raise PermissionError("角色与工作助手不匹配")
        request = request.validated()
        task_type = (
            TaskType.DOCTOR_WORK_ASSISTANT
            if role == "doctor"
            else TaskType.ASSISTANT_WORK_ASSISTANT
        )
        payload = {
            "page": request.page,
            "feature_key": request.feature_key,
            "message": request.message,
            "assistant_session_id": request.session_id,
        }
        task = self.repository.create(
            owner_user_id=owner_user_id,
            role=role,
            task_type=task_type,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            self._submit(task.task_id)
        except Exception:
            self.repository.fail(
                task.task_id,
                "TASK_QUEUE_FAILED",
                "任务未能进入执行队列",
            )
            raise
        return TaskCreationResult(mode="asynchronous", task=task)

    def get(self, owner_user_id: str, task_id: str) -> TaskSnapshot:
        return self.repository.get(owner_user_id, task_id)

    def cancel(self, owner_user_id: str, task_id: str) -> TaskSnapshot:
        return self.repository.request_cancel(owner_user_id, task_id)

    def events(
        self,
        owner_user_id: str,
        task_id: str,
        *,
        after: int = 0,
    ) -> list[TaskEvent]:
        if after < 0:
            raise ValueError("Last-Event-ID 不合法")
        return self.repository.list_events(owner_user_id, task_id, after=after)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.repository.fail_incomplete(
                "SERVICE_SHUTDOWN",
                "服务已关闭，未完成内容未保存为成功结果",
            )
            self.executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, task_id: str) -> None:
        with self._close_lock:
            if self._closed:
                raise RuntimeError("任务执行器已关闭")
            self.executor.submit(self._run, task_id)

    def _run(self, task_id: str) -> None:
        if not self.repository.start(task_id):
            return
        row = self.repository.get_for_worker(task_id)
        if not row:
            return
        deadline = time.monotonic() + float(row["timeout_seconds"])
        emitted = False

        def check_stop() -> None:
            if self.repository.should_cancel(task_id):
                raise TaskCancelledError("任务已取消")
            if time.monotonic() >= deadline:
                raise TaskTimedOutError("模型请求超时")

        def on_delta(text: str) -> None:
            nonlocal emitted
            check_stop()
            try:
                self.repository.append_delta(task_id, text)
            except RuntimeError:
                if self.repository.should_cancel(task_id):
                    raise TaskCancelledError("任务已取消")
                raise
            emitted = True

        try:
            payload = row["input"]
            if row["task_type"] == TaskType.PATIENT_PAGE_ASSISTANT.value:
                from app.schemas.page_assistant import AssistantEvent, PatientPage

                result = self.agents.patient_page_assistant.run_stream(
                    requester_user_id=row["owner_user_id"],
                    request=PageAssistantRequest(
                        page=PatientPage(payload["page"]),
                        message=payload["message"],
                        session_id=payload.get("assistant_session_id"),
                        feature_key=payload["feature_key"],
                        event=AssistantEvent(payload["event"]),
                    ),
                    on_delta=on_delta,
                    should_stop=check_stop,
                )
            else:
                result = self.agents.work_assistant.run_stream(
                    requester_user_id=row["owner_user_id"],
                    role=row["role"],
                    request=WorkAssistantRequest(
                        page=payload["page"],
                        feature_key=payload["feature_key"],
                        message=payload["message"],
                        session_id=payload.get("assistant_session_id"),
                    ),
                    on_delta=on_delta,
                    should_stop=check_stop,
                )
            check_stop()
            output = asdict(result)
            self._validate_output(output)
            if not emitted and output.get("answer"):
                for offset in range(0, len(output["answer"]), 80):
                    on_delta(output["answer"][offset : offset + 80])
            check_stop()
            if not self.repository.complete(task_id, output):
                if self.repository.should_cancel(task_id):
                    self.repository.cancel(task_id)
                else:
                    self.repository.fail(
                        task_id,
                        "INVALID_TASK_STATE",
                        "任务无法完成",
                    )
        except TaskCancelledError:
            self.repository.cancel(task_id)
        except TaskTimedOutError:
            self.repository.fail(task_id, "TASK_TIMEOUT", "模型请求已超时")
        except Exception:
            self.repository.fail(
                task_id,
                "TASK_EXECUTION_FAILED",
                "任务执行失败，未完成内容不会作为成功结果",
            )

    @staticmethod
    def _validate_output(output: dict) -> None:
        answer = output.get("answer")
        if not isinstance(answer, str):
            raise ValueError("任务输出缺少完整 answer")
        if len(answer) > 4_000:
            raise ValueError("任务输出超过安全长度")
