from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings
from app.llm.base import LLMMessage
from app.llm.deepseek import DeepSeekLLM


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body.read()


class FakeStreamResponse:
    def __init__(self, lines: list[str]):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.lines)


class DeepSeekLLMTests(unittest.TestCase):
    def test_reads_key_from_dotenv_without_returning_it_in_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text('DEEPSEEK_API_KEY="replace-unit-test-key"\n', encoding="utf-8")
            settings = Settings(dotenv_file=dotenv)
            self.assertEqual(settings.load_deepseek_api_key(), "replace-unit-test-key")

    def test_chat_completion_contract(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                {"choices": [{"message": {"content": "简短回答"}}]}
            )

        llm = DeepSeekLLM(api_key="secret", opener=opener)
        answer = llm.generate(
            [LLMMessage("system", "规则"), LLMMessage("user", "问题")]
        )
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(answer, "简短回答")
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("secret", captured["request"].data.decode("utf-8"))
        self.assertEqual(captured["timeout"], 20.0)

    def test_stream_completion_contract(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            return FakeStreamResponse([
                'data: {"choices":[{"delta":{"content":"你"}}]}\n',
                'data: {"choices":[{"delta":{"content":"好"}}]}\n',
                "data: [DONE]\n",
            ])

        llm = DeepSeekLLM(api_key="secret", opener=opener)
        chunks = list(llm.stream([LLMMessage("user", "问题")]))
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(chunks, ["你", "好"])
        self.assertTrue(payload["stream"])


if __name__ == "__main__":
    unittest.main()
