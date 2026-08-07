from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WorkAssistantRequest:
    page: str
    feature_key: str
    message: str
    session_id: str | None = None

    def validated(self) -> "WorkAssistantRequest":
        page = self.page.strip()
        feature = self.feature_key.strip()
        message = self.message.strip()
        if not page or len(page) > 64:
            raise ValueError("page 不合法")
        if not feature or len(feature) > 64:
            raise ValueError("feature_key 不合法")
        if not message or len(message) > 2000:
            raise ValueError("message 长度必须在 1 到 2000 之间")
        return WorkAssistantRequest(page, feature, message, self.session_id)


@dataclass(frozen=True, slots=True)
class ToolCallSummary:
    tool_call_id: str
    tool_name: str
    status: str
    result_summary: dict
    latency_ms: int


@dataclass(frozen=True, slots=True)
class WorkAssistantResponse:
    response_type: str
    answer: str
    session_id: str
    tool_calls: list[ToolCallSummary] = field(default_factory=list)
    degraded: bool = False


class WorkAssistantPermissionError(PermissionError):
    pass
