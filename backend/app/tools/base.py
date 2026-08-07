from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ToolContext:
    user_id: str
    role: str


class ReadOnlyTool(Protocol):
    name: str
    description: str
    allowed_roles: frozenset[str]
    input_model: type[BaseModel]

    def execute(self, context: ToolContext, arguments: BaseModel) -> dict[str, Any]: ...
