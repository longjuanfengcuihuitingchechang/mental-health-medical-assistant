from __future__ import annotations

import json
from collections.abc import Iterator
from collections.abc import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.llm.base import LLMMessage


class DeepSeekError(RuntimeError):
    pass


class DeepSeekLLM:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout_seconds: float = 20.0,
        opener: Callable = urlopen,
    ):
        if not api_key.strip():
            raise ValueError("DeepSeek API Key 不能为空")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("DEEPSEEK_BASE_URL 必须是有效的 HTTPS 地址")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    def generate(self, messages: Sequence[LLMMessage]) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "thinking": {"type": "disabled"},
                "temperature": 0.2,
                "max_tokens": 300,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise DeepSeekError("DeepSeek 当前不可用") from error
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError("DeepSeek 返回了空内容")
        return content.strip()

    def stream(self, messages: Sequence[LLMMessage]) -> Iterator[str]:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "thinking": {"type": "disabled"},
                "temperature": 0.2,
                "max_tokens": 300,
                "stream": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        received = False
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    item = json.loads(data)
                    content = item["choices"][0].get("delta", {}).get("content")
                    if isinstance(content, str) and content:
                        received = True
                        yield content
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DeepSeekError("DeepSeek 流式响应当前不可用") from error
        if not received:
            raise DeepSeekError("DeepSeek 返回了空流")
