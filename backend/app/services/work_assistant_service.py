from __future__ import annotations

import time
from datetime import date
from collections.abc import Callable

from app.llm.base import BaseLLM, LLMMessage
from app.repositories.work_assistant_repository import WorkAssistantRepository
from app.schemas.work_assistant import (
    ToolCallSummary,
    WorkAssistantPermissionError,
    WorkAssistantRequest,
    WorkAssistantResponse,
)
from app.schemas.async_tasks import TaskCancelledError, TaskTimedOutError
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


class WorkAssistantService:
    MAX_STEPS = 2

    def __init__(self, repository: WorkAssistantRepository, registry: ToolRegistry, llm: BaseLLM):
        self.repository = repository
        self.registry = registry
        self.llm = llm

    def respond(
        self,
        user_id: str,
        role: str,
        request: WorkAssistantRequest,
        *,
        on_delta: Callable[[str], None] | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> WorkAssistantResponse:
        request = request.validated()
        user = self.repository.get_user(user_id)
        if not user or user["role"] != role or role not in {"doctor", "assistant"} or user["account_status"] != "active" or user["blacklisted"]:
            raise WorkAssistantPermissionError("当前账号无权使用工作助手")
        try:
            session_id = self.repository.ensure_session(user_id, role, request.session_id, request.page)
        except PermissionError as exc:
            raise WorkAssistantPermissionError(str(exc)) from exc
        name, arguments = self._select_tool(role, request.message)
        run_id = self.repository.create_run(user_id, f"{role}_work_assistant", session_id, {"page": request.page, "feature_key": request.feature_key, "message": request.message[:500]})
        started = time.monotonic()
        try:
            result = self.registry.execute(name, ToolContext(user_id, role), arguments)
            latency = int((time.monotonic() - started) * 1000)
            call_id = self.repository.save_tool_call(run_id, name, "SUCCEEDED", latency, result)
            answer, degraded = self._answer(
                role,
                name,
                result,
                on_delta=on_delta,
                should_stop=should_stop,
            )
            summary = ToolCallSummary(call_id, name, "SUCCEEDED", result, latency)
            self.repository.append_pair(session_id, request.page, request.feature_key, request.message, answer)
            self.repository.finish_run(run_id, "SUCCEEDED", {"answer": answer})
            return WorkAssistantResponse("tool_result", answer, session_id, [summary], degraded)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            self.repository.save_tool_call(run_id, name, "FAILED", latency, {}, type(exc).__name__)
            self.repository.finish_run(run_id, "FAILED", None, type(exc).__name__)
            raise

    @staticmethod
    def _select_tool(role: str, message: str) -> tuple[str, dict]:
        today = date.today().isoformat()
        if "库存" in message or "药" in message:
            return "search_medicine_inventory", {"keyword": ""}
        if "夜班" in message:
            return "get_night_shift", {"date": today}
        if role == "assistant":
            if "医生" in message or "排班" in message or "安排" in message:
                return "get_doctor_schedule", {"date": today}
            return "get_coordination_queue", {}
        if "队列" in message or "患者" in message or "预约" in message:
            return "get_my_appointment_queue", {}
        return "get_my_schedule", {}

    def _answer(
        self,
        role: str,
        tool_name: str,
        result: dict,
        *,
        on_delta: Callable[[str], None] | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> tuple[str, bool]:
        fallback = f"查询完成：{tool_name} 返回 {result.get('count', 1 if result.get('item') else 0)} 条记录。"
        if result.get("source_status") == "empty":
            fallback = "当前药物库存数据源为空，没有可展示的库存记录。"
        messages = [
                LLMMessage("system", "你是医疗机构工作助手。只解释给定的真实只读查询结果，不诊断、不处方、不编造；中文不超过150字。"),
                LLMMessage("user", f"角色={role}; 工具={tool_name}; 结果={result}"),
            ]
        try:
            if on_delta and callable(getattr(self.llm, "stream", None)):
                parts = []
                length = 0
                for chunk in self.llm.stream(messages):
                    if should_stop:
                        should_stop()
                    text = str(chunk)[: max(0, 500 - length)]
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
                    on_delta(answer[:500])
            return (answer[:500] or fallback, False)
        except (TaskCancelledError, TaskTimedOutError):
            raise
        except Exception:
            if on_delta:
                raise
            return fallback, True
