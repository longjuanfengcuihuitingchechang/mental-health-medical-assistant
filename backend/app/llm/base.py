from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


class BaseLLM(Protocol):
    """可替换的 LLM 端口；具体云端或本地模型适配器以后注入。"""

    def generate(self, messages: Sequence[LLMMessage]) -> str: ...

    def stream(self, messages: Sequence[LLMMessage]) -> Iterator[str]: ...


class RuleBasedPageLLM:
    """无模型配置时的安全降级，不伪装成真实诊疗模型。"""

    def generate(self, messages: Sequence[LLMMessage]) -> str:
        user_text = messages[-1].content if messages else ""
        return (
            "我可以说明当前页面的功能和操作方法。"
            f"你刚才问的是“{user_text[:80]}”。"
            "如果你希望正式就诊，请告诉我“我要就诊”，我会带你进入患者诊疗页选择医生。"
        )

    def stream(self, messages: Sequence[LLMMessage]) -> Iterator[str]:
        yield self.generate(messages)
