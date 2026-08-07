from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.agents.page_assistant_agent import PatientPageAssistantAgent
from app.db.connection import SQLiteConnectionFactory
from app.llm.base import LLMMessage
from app.repositories.page_assistant_repository import PageAssistantRepository
from app.schemas.page_assistant import (
    AgeGroup,
    AssistantResponseType,
    DoctorAvailability,
    PageAssistantRequest,
    PatientAssistantPermissionError,
    PatientPage,
)
from app.services.page_assistant_service import PatientPageAssistantService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class FakeLLM:
    def __init__(self, answer: str = "这是当前页面的操作说明。"):
        self.answer = answer
        self.calls: list[list[LLMMessage]] = []

    def generate(self, messages):
        self.calls.append(list(messages))
        return self.answer


class FailingLLM:
    def generate(self, messages):
        raise RuntimeError("model unavailable")


class PatientPageAssistantAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.executemany(
            """
            INSERT INTO users (id, account, password_hash, display_name, role, account_status)
            VALUES (?, ?, 'unused', ?, ?, 'active')
            """,
            [
                ("patient-1", "P001", "小患者", "patient"),
                ("older-1", "P002", "王老师", "patient"),
                ("doctor-1", "D001", "李医生", "doctor"),
                ("doctor-2", "D002", "周医生", "doctor"),
                ("admin-1", "A001", "管理员", "admin"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO person_profiles (
                user_id, id_card_fingerprint, id_card_masked, phone_masked,
                email_masked, birth_date, gender, created_at, updated_at
            ) VALUES (?, ?, 'mask', 'mask', 'mask', ?, 'unknown', ?, ?)
            """,
            [
                ("patient-1", "fp1", "2012-08-07", "2026-08-06T08:00:00+00:00", "2026-08-06T08:00:00+00:00"),
                ("older-1", "fp2", "1950-01-01", "2026-08-06T08:00:00+00:00", "2026-08-06T08:00:00+00:00"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO doctor_profiles (
                user_id, employee_no, department, professional_title, employment_status
            ) VALUES (?, ?, '心理科', '医师', 'active')
            """,
            [("doctor-1", "D001"), ("doctor-2", "D002")],
        )
        connection.executemany(
            """
            INSERT INTO doctor_availability (
                doctor_user_id, availability_status, status_since,
                expected_available_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("doctor-1", "working", "2026-08-06T00:00:00+00:00", None, "2026-08-06T00:00:00+00:00"),
                ("doctor-2", "on_leave", "2026-08-01T00:00:00+00:00", "2026-08-09T08:00:00+00:00", "2026-08-06T00:00:00+00:00"),
            ],
        )
        connection.execute(
            """
            INSERT INTO clinical_visit_summaries (
                id, patient_user_id, doctor_user_id, visited_at, created_at
            ) VALUES ('visit-1', 'patient-1', 'doctor-2',
                      '2026-07-01T08:00:00+00:00', '2026-07-01T08:00:00+00:00')
            """
        )
        connection.executemany(
            """
            INSERT INTO consultation_queue (
                id, doctor_user_id, patient_user_id, status, joined_at, updated_at
            ) VALUES (?, 'doctor-1', ?, 'waiting', ?, ?)
            """,
            [
                ("queue-1", "older-1", "2026-08-06T06:00:00+00:00", "2026-08-06T06:00:00+00:00"),
                ("queue-2", "patient-1", "2026-08-06T07:00:00+00:00", "2026-08-06T07:00:00+00:00"),
            ],
        )
        connection.commit()
        connection.close()

        self.llm = FakeLLM()
        repository = PageAssistantRepository(SQLiteConnectionFactory(self.database_path))
        service = PatientPageAssistantService(
            repository,
            self.llm,
            clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        )
        self.agent = PatientPageAssistantAgent(service)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_page_entry_introduces_only_current_page(self) -> None:
        response = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.ASSESSMENTS),
        )
        self.assertEqual(response.response_type, AssistantResponseType.PAGE_INTRO)
        self.assertIn("心理测评", response.answer)
        self.assertEqual(response.age_group, AgeGroup.CHILD)
        self.assertEqual(self.llm.calls, [])

    def test_page_question_calls_llm_with_scope_and_age(self) -> None:
        response = self.agent.run(
            requester_user_id="older-1",
            request=PageAssistantRequest(PatientPage.WELLBEING, "怎么记录今天的情绪？"),
        )
        self.assertEqual(response.response_type, AssistantResponseType.PAGE_ANSWER)
        self.assertEqual(response.age_group, AgeGroup.OLDER_ADULT)
        self.assertIn("不催促", self.llm.calls[0][0].content)
        self.assertIn("不得诊断", self.llm.calls[0][0].content)

    def test_other_page_question_returns_navigation_without_llm(self) -> None:
        response = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.WELLBEING, "量表分数在哪里看？"),
        )
        self.assertEqual(response.response_type, AssistantResponseType.OUT_OF_SCOPE)
        self.assertEqual(response.suggested_page, PatientPage.ASSESSMENTS)
        self.assertEqual(self.llm.calls, [])

    def test_care_navigation_prioritizes_previous_doctor_and_reports_status(self) -> None:
        response = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.OVERVIEW, "我要就诊"),
        )
        self.assertEqual(response.response_type, AssistantResponseType.CARE_NAVIGATION)
        self.assertEqual(response.suggested_page, PatientPage.CARE)
        self.assertTrue(response.requires_guardian_support)
        self.assertEqual(response.doctors[0].doctor_user_id, "doctor-2")
        self.assertTrue(response.doctors[0].is_previous_doctor)
        self.assertEqual(response.doctors[0].availability, DoctorAvailability.ON_LEAVE)
        self.assertEqual(response.doctors[0].leave_remaining_days, 3)
        working = next(item for item in response.doctors if item.doctor_user_id == "doctor-1")
        self.assertEqual(working.queue_length, 2)
        self.assertEqual(working.patient_queue_position, 2)
        self.assertEqual(self.llm.calls, [])

    def test_crisis_support_bypasses_llm(self) -> None:
        response = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.SUPPORT, "我不想活了"),
        )
        self.assertEqual(response.response_type, AssistantResponseType.CRISIS_SUPPORT)
        self.assertEqual(response.crisis_contacts, ["12356", "110", "120"])
        self.assertEqual(self.llm.calls, [])

    def test_non_patient_cannot_use_patient_agent(self) -> None:
        with self.assertRaises(PatientAssistantPermissionError):
            self.agent.run(
                requester_user_id="admin-1",
                request=PageAssistantRequest(PatientPage.OVERVIEW),
            )

    def test_age_boundaries_are_deterministic(self) -> None:
        today = datetime(2026, 8, 6, tzinfo=UTC).date()
        classify = PatientPageAssistantService._age_group
        self.assertEqual(classify("2008-08-07", today), AgeGroup.CHILD)
        self.assertEqual(classify("2008-08-06", today), AgeGroup.ADULT)
        self.assertEqual(classify("1961-08-07", today), AgeGroup.ADULT)
        self.assertEqual(classify("1961-08-06", today), AgeGroup.OLDER_ADULT)

    def test_model_failure_does_not_break_current_page(self) -> None:
        repository = PageAssistantRepository(
            SQLiteConnectionFactory(self.database_path)
        )
        agent = PatientPageAssistantAgent(
            PatientPageAssistantService(
                repository,
                FailingLLM(),
                clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
            )
        )
        response = agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.WELLBEING, "如何保存？"),
        )
        self.assertEqual(response.response_type, AssistantResponseType.PAGE_ANSWER)
        self.assertIn("暂不可用", response.answer)

    def test_first_eight_opens_introduce_and_ninth_is_suppressed(self) -> None:
        session_id = None
        responses = []
        for _ in range(9):
            response = self.agent.run(
                requester_user_id="patient-1",
                request=PageAssistantRequest(
                    PatientPage.RESOURCES,
                    session_id=session_id,
                    feature_key="professional_help",
                ),
            )
            session_id = response.session_id
            responses.append(response)
        self.assertTrue(all(item.answer for item in responses[:8]))
        self.assertTrue(responses[8].introduction_suppressed)
        self.assertEqual(responses[8].usage_count, 9)

        connection = sqlite3.connect(self.database_path)
        usage = connection.execute(
            """
            SELECT usage_count, introduction_count FROM patient_feature_usage
            WHERE patient_user_id = 'patient-1'
              AND page = 'resources' AND feature_key = 'professional_help'
            """
        ).fetchone()
        log_count = connection.execute(
            "SELECT COUNT(*) FROM patient_feature_usage_logs"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(usage, (9, 8))
        self.assertEqual(log_count, 9)

    def test_conversation_memory_survives_page_change(self) -> None:
        first = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.OVERVIEW, "这个按钮怎么用？"),
        )
        self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(
                PatientPage.WELLBEING,
                "当前功能怎么操作？",
                session_id=first.session_id,
            ),
        )
        second_call = self.llm.calls[1]
        self.assertEqual(
            [message.role for message in second_call],
            ["system", "user", "assistant", "user"],
        )
        self.assertIn("这个按钮怎么用", second_call[1].content)

    def test_other_patient_cannot_reuse_session(self) -> None:
        first = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.OVERVIEW),
        )
        with self.assertRaises(PatientAssistantPermissionError):
            self.agent.run(
                requester_user_id="older-1",
                request=PageAssistantRequest(
                    PatientPage.OVERVIEW,
                    session_id=first.session_id,
                ),
            )

    def test_history_can_be_restored_only_by_session_owner(self) -> None:
        response = self.agent.run(
            requester_user_id="patient-1",
            request=PageAssistantRequest(PatientPage.OVERVIEW, "怎样查看趋势？"),
        )
        history = self.agent.history(
            requester_user_id="patient-1",
            session_id=response.session_id,
        )
        self.assertEqual([item.role for item in history.messages], ["user", "assistant"])
        with self.assertRaises(PatientAssistantPermissionError):
            self.agent.history(
                requester_user_id="older-1",
                session_id=response.session_id,
            )


if __name__ == "__main__":
    unittest.main()
