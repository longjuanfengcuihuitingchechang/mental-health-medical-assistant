from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.llm.base import RuleBasedPageLLM
from app.repositories.work_assistant_repository import WorkAssistantRepository
from app.schemas.work_assistant import WorkAssistantPermissionError, WorkAssistantRequest
from app.services.work_assistant_service import WorkAssistantService
from app.tools.base import ToolContext
from app.tools.work_tools import build_work_tool_registry
from app.db.connection import SQLiteConnectionFactory


class WorkAssistantAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.db"
        schema = Path(__file__).parents[1] / "db" / "schema.sql"
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(schema.read_text(encoding="utf-8"))
            connection.executemany(
                "INSERT INTO users (id,account,display_name,role) VALUES (?, ?, ?, ?)",
                [
                    ("doctor-1", "D901", "测试医生", "doctor"),
                    ("doctor-2", "D902", "其他医生", "doctor"),
                    ("assistant-1", "S901", "测试助理", "assistant"),
                ],
            )
            connection.executemany(
                "INSERT INTO doctor_profiles (user_id,employee_no,employment_status) VALUES (?, ?, 'active')",
                [("doctor-1", "D901"), ("doctor-2", "D902")],
            )
            connection.commit()
        finally:
            connection.close()
        self.repository = WorkAssistantRepository(SQLiteConnectionFactory(self.database))
        self.registry = build_work_tool_registry(self.repository)
        self.service = WorkAssistantService(self.repository, self.registry, RuleBasedPageLLM())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_role_tool_visibility_and_denial(self) -> None:
        self.assertIn("get_my_schedule", self.registry.visible_names("doctor"))
        self.assertNotIn("get_coordination_queue", self.registry.visible_names("doctor"))
        with self.assertRaises(WorkAssistantPermissionError):
            self.registry.execute("get_coordination_queue", ToolContext("doctor-1", "doctor"), {})

    def test_doctor_query_persists_real_run_and_memory(self) -> None:
        response = self.service.respond(
            "doctor-1",
            "doctor",
            WorkAssistantRequest("schedule", "daily", "查询我的排班"),
        )
        self.assertEqual(response.tool_calls[0].tool_name, "get_my_schedule")
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT status FROM agent_runs").fetchone()[0], "SUCCEEDED")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM work_assistant_messages").fetchone()[0], 2)
        finally:
            connection.close()

        with self.assertRaises(WorkAssistantPermissionError):
            self.service.respond(
                "doctor-2",
                "doctor",
                WorkAssistantRequest("schedule", "daily", "查询排班", response.session_id),
            )

    def test_empty_inventory_is_truthful(self) -> None:
        response = self.service.respond(
            "assistant-1",
            "assistant",
            WorkAssistantRequest("inventory", "search", "查询药物库存"),
        )
        summary = response.tool_calls[0].result_summary
        self.assertEqual(summary["source_status"], "empty")
        self.assertEqual(summary["items"], [])


if __name__ == "__main__":
    unittest.main()
