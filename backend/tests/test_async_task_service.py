from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.db.connection import SQLiteConnectionFactory
from app.repositories.async_task_repository import AsyncTaskRepository
from app.schemas.async_tasks import TaskEventType, TaskStatus
from app.schemas.async_tasks import TaskType
from app.schemas.page_assistant import (
    AgeGroup,
    AssistantResponseType,
    PageAssistantRequest,
    PageAssistantResponse,
    PatientPage,
)
from app.schemas.work_assistant import WorkAssistantRequest, WorkAssistantResponse
from app.services.async_task_service import AsyncTaskService


SCHEMA = Path(__file__).parents[1] / "db" / "schema.sql"


class FakePatientAgent:
    def __init__(self):
        self.sync_calls = 0

    def run(self, *, requester_user_id, request):
        self.sync_calls += 1
        return PageAssistantResponse(
            response_type=AssistantResponseType.CRISIS_SUPPORT,
            page=request.page,
            answer="请立即联系现实中的可信任人员，并拨打 110、120 或 12356。",
            age_group=AgeGroup.ADULT,
            crisis_contacts=["12356", "110", "120"],
        )


class StreamingWorkAgent:
    def __init__(self, *, delay: float = 0.0, chunks: int = 2):
        self.delay = delay
        self.chunks = chunks

    def run_stream(self, *, requester_user_id, role, request, on_delta, should_stop):
        parts = []
        for index in range(self.chunks):
            should_stop()
            text = f"片段{index}"
            on_delta(text)
            parts.append(text)
            if self.delay:
                time.sleep(self.delay)
        return WorkAssistantResponse(
            response_type="tool_result",
            answer="".join(parts),
            session_id="session-test",
        )


class AsyncTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "tasks.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        connection.executemany(
            """INSERT INTO users (id,account,password_hash,display_name,role)
               VALUES (?,?,?,?,?)""",
            [
                ("patient-1", "P901", "unused", "患者", "patient"),
                ("doctor-1", "D901", "unused", "医生", "doctor"),
                ("doctor-2", "D902", "unused", "另一位医生", "doctor"),
            ],
        )
        connection.commit()
        connection.close()
        self.repository = AsyncTaskRepository(SQLiteConnectionFactory(self.database))
        self.services: list[AsyncTaskService] = []

    def tearDown(self):
        for service in self.services:
            service.close()
        self.temp.cleanup()

    def build_service(self, work_agent, *, timeout=1.0):
        service = AsyncTaskService(
            self.repository,
            SimpleNamespace(
                patient_page_assistant=FakePatientAgent(),
                work_assistant=work_agent,
            ),
            timeout_seconds=timeout,
            max_workers=1,
        )
        self.services.append(service)
        return service

    def wait_terminal(self, owner, task_id, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.repository.get(owner, task_id)
            if snapshot.status.terminal:
                return snapshot
            time.sleep(0.01)
        self.fail("任务未在测试时限内终止")

    def test_crisis_precheck_is_synchronous_and_creates_no_task(self):
        service = self.build_service(StreamingWorkAgent())
        result = service.create_patient_task(
            owner_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.SUPPORT, "我不想活了"),
        )
        self.assertEqual(result.mode, "synchronous")
        self.assertTrue(result.crisis)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM async_tasks").fetchone()[0], 0)
        finally:
            connection.close()

    def test_success_requires_terminal_event_and_supports_resume(self):
        service = self.build_service(StreamingWorkAgent())
        created = service.create_work_task(
            owner_user_id="doctor-1",
            role="doctor",
            request=WorkAssistantRequest("schedule", "daily", "查询排班"),
        )
        task_id = created.task.task_id
        snapshot = self.wait_terminal("doctor-1", task_id)
        self.assertEqual(snapshot.status, TaskStatus.SUCCEEDED)
        events = service.events("doctor-1", task_id)
        types = [event.event_type for event in events]
        self.assertEqual(types[0], TaskEventType.CREATED)
        self.assertIn(TaskEventType.DELTA, types)
        self.assertEqual(types[-1], TaskEventType.COMPLETED)
        self.assertEqual([event.event_id for event in events], list(range(1, len(events) + 1)))
        resumed = service.events("doctor-1", task_id, after=events[1].event_id)
        self.assertEqual(resumed[0].event_id, events[2].event_id)
        with self.assertRaises(PermissionError):
            service.get("doctor-2", task_id)

    def test_cancelled_partial_output_is_never_completed(self):
        service = self.build_service(StreamingWorkAgent(delay=0.02, chunks=50))
        created = service.create_work_task(
            owner_user_id="doctor-1",
            role="doctor",
            request=WorkAssistantRequest("schedule", "daily", "查询排班"),
        )
        time.sleep(0.04)
        service.cancel("doctor-1", created.task.task_id)
        snapshot = self.wait_terminal("doctor-1", created.task.task_id)
        self.assertEqual(snapshot.status, TaskStatus.CANCELLED)
        types = [event.event_type for event in service.events("doctor-1", created.task.task_id)]
        self.assertIn(TaskEventType.CANCELLED, types)
        self.assertNotIn(TaskEventType.COMPLETED, types)

    def test_timeout_fails_and_never_emits_completed(self):
        service = self.build_service(
            StreamingWorkAgent(delay=0.03, chunks=20),
            timeout=0.04,
        )
        created = service.create_work_task(
            owner_user_id="doctor-1",
            role="doctor",
            request=WorkAssistantRequest("schedule", "daily", "查询排班"),
        )
        snapshot = self.wait_terminal("doctor-1", created.task.task_id)
        self.assertEqual(snapshot.status, TaskStatus.FAILED)
        self.assertEqual(snapshot.error_code, "TASK_TIMEOUT")
        types = [event.event_type for event in service.events("doctor-1", created.task.task_id)]
        self.assertEqual(types[-1], TaskEventType.FAILED)
        self.assertNotIn(TaskEventType.COMPLETED, types)

    def test_service_start_recovers_incomplete_tasks_as_failed(self):
        task = self.repository.create(
            owner_user_id="doctor-1",
            role="doctor",
            task_type=TaskType.DOCTOR_WORK_ASSISTANT,
            payload={"page": "schedule"},
            timeout_seconds=10,
        )
        self.build_service(StreamingWorkAgent())
        snapshot = self.repository.get("doctor-1", task.task_id)
        self.assertEqual(snapshot.status, TaskStatus.FAILED)
        self.assertEqual(snapshot.error_code, "SERVICE_RESTARTED")
        self.assertEqual(
            self.repository.list_events("doctor-1", task.task_id)[-1].event_type,
            TaskEventType.FAILED,
        )


if __name__ == "__main__":
    unittest.main()
