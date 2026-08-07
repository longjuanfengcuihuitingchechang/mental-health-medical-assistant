from __future__ import annotations

from typing import Any

from app.schemas.work_assistant import WorkAssistantPermissionError
from app.tools.base import ReadOnlyTool, ToolContext


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ReadOnlyTool] = {}

    def register(self, tool: ReadOnlyTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"重复工具名称：{tool.name}")
        self._tools[tool.name] = tool

    def visible_names(self, role: str) -> list[str]:
        return sorted(
            name for name, tool in self._tools.items() if role in tool.allowed_roles
        )

    def execute(
        self, name: str, context: ToolContext, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError("未知工具")
        if context.role not in tool.allowed_roles:
            raise WorkAssistantPermissionError("当前角色无权使用该工具")
        validated = tool.input_model.model_validate(arguments)
        result = tool.execute(context, validated)
        if not isinstance(result, dict):
            raise RuntimeError("工具返回结构不合法")
        return result
