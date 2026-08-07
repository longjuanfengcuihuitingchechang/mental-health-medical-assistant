from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.agents.appointment_agent import (
    AppointmentCapacityAgent,
    AppointmentDecisionAgent,
    NightShiftAgent,
    PatientAppointmentAgent,
)
from app.db.connection import SQLiteConnectionFactory
from app.repositories.appointment_repository import AppointmentRepository
from app.schemas.appointments import (
    AppointmentConflictError,
    AppointmentEligibilityError,
    AppointmentStatus,
    CapacityRequest,
    CommunicationMode,
    CreateAppointmentRequest,
    DoctorAppointmentDecision,
    DoctorDecisionRequest,
    NightShiftRequest,
    PatientAppointmentDecision,
    PatientDecisionRequest,
)
from app.services.appointment_service import AppointmentService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class GentleLLM:
    def generate(self, messages):
        return "很抱歉，这次暂时无法安排。你可以选择其他医生，我们会继续协助。"


class AppointmentAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.executemany(
            """
            INSERT INTO users (id, account, display_name, role, account_status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            [
                ("patient-9", "P009", "患者九", "patient"),
                ("patient-10", "P010", "患者十", "patient"),
                ("patient-11", "P011", "患者十一", "patient"),
                ("doctor-1", "D001", "李医生", "doctor"),
                ("doctor-2", "D002", "周医生", "doctor"),
                ("assistant-1", "S001", "助理一", "assistant"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO doctor_profiles (user_id, employee_no, employment_status)
            VALUES (?, ?, 'active')
            """,
            [("doctor-1", "D001"), ("doctor-2", "D002")],
        )
        connection.execute(
            """
            INSERT INTO assistant_profiles (
                user_id, employee_no, employment_status, created_at, updated_at
            ) VALUES ('assistant-1', 'S001', 'active', '2026-08-06', '2026-08-06')
            """
        )
        for patient_id, count in (("patient-9", 9), ("patient-10", 10), ("patient-11", 10)):
            for index in range(count):
                connection.execute(
                    """
                    INSERT INTO clinical_visit_summaries (
                        id, patient_user_id, doctor_user_id, visited_at, status, created_at
                    ) VALUES (?, ?, 'doctor-1', ?, 'completed', ?)
                    """,
                    (f"{patient_id}-{index}", patient_id, f"2026-07-{index + 1:02d}", "2026-07-01"),
                )
        connection.commit()
        connection.close()

        repository = AppointmentRepository(SQLiteConnectionFactory(self.database_path))
        service = AppointmentService(
            repository,
            GentleLLM(),
            clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        )
        self.capacity_agent = AppointmentCapacityAgent(service)
        self.patient_agent = PatientAppointmentAgent(service)
        self.decision_agent = AppointmentDecisionAgent(service)
        self.night_agent = NightShiftAgent(service)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ten_completed_visits_are_required(self) -> None:
        with self.assertRaises(AppointmentEligibilityError):
            self.patient_agent.run(
                requester_user_id="patient-9",
                request=CreateAppointmentRequest("doctor-1", "2026-08-07"),
            )
        response = self.patient_agent.run(
            requester_user_id="patient-10",
            request=CreateAppointmentRequest("doctor-1", "2026-08-07"),
        )
        self.assertEqual(response.completed_visit_count, 10)

    def test_capacity_and_over_capacity_workflow(self) -> None:
        capacity = self.capacity_agent.run(
            requester_user_id="doctor-1",
            request=CapacityRequest("2026-08-07", 1),
        )
        self.assertEqual(capacity.capacity, 1)

        first = self.patient_agent.run(
            requester_user_id="patient-10",
            request=CreateAppointmentRequest("doctor-1", "2026-08-07"),
        )
        self.assertEqual(first.status, AppointmentStatus.QUEUED)
        self.assertEqual(first.queue_position, 1)

        second = self.patient_agent.run(
            requester_user_id="patient-11",
            request=CreateAppointmentRequest("doctor-1", "2026-08-07"),
        )
        self.assertEqual(second.status, AppointmentStatus.AWAITING_PATIENT_DECISION)
        self.assertEqual(second.appointment_count, 2)

        continued = self.patient_agent.decide(
            requester_user_id="patient-11",
            request=PatientDecisionRequest(
                second.appointment_id,
                PatientAppointmentDecision.CONTINUE_REQUEST,
            ),
        )
        self.assertEqual(continued.status, AppointmentStatus.AWAITING_DOCTOR_DECISION)
        pending = self.decision_agent.pending(requester_user_id="doctor-1")
        self.assertEqual([item.appointment_id for item in pending], [second.appointment_id])
        self.assertEqual(len(self.decision_agent.pending(requester_user_id="assistant-1")), 1)

        accepted = self.decision_agent.decide(
            requester_user_id="doctor-1",
            request=DoctorDecisionRequest(
                second.appointment_id,
                DoctorAppointmentDecision.ACCEPT,
            ),
        )
        self.assertEqual(accepted.status, AppointmentStatus.QUEUED_OVER_CAPACITY)
        self.assertIn("仍需", accepted.patient_message)

    def test_gentle_decline_is_audited(self) -> None:
        self.capacity_agent.run(
            requester_user_id="doctor-1",
            request=CapacityRequest("2026-08-08", 0),
        )
        appointment = self.patient_agent.run(
            requester_user_id="patient-10",
            request=CreateAppointmentRequest("doctor-1", "2026-08-08"),
        )
        self.patient_agent.decide(
            requester_user_id="patient-10",
            request=PatientDecisionRequest(
                appointment.appointment_id,
                PatientAppointmentDecision.CONTINUE_REQUEST,
            ),
        )
        declined = self.decision_agent.decide(
            requester_user_id="doctor-1",
            request=DoctorDecisionRequest(
                appointment.appointment_id,
                DoctorAppointmentDecision.DECLINE,
                CommunicationMode.GENTLE,
            ),
        )
        self.assertEqual(declined.status, AppointmentStatus.DECLINED_GENTLE)
        connection = sqlite3.connect(self.database_path)
        event_count = connection.execute(
            "SELECT COUNT(*) FROM appointment_events WHERE appointment_id = ?",
            (appointment.appointment_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(event_count, 3)

    def test_only_next_two_days_are_configurable(self) -> None:
        with self.assertRaises(ValueError):
            self.capacity_agent.run(
                requester_user_id="doctor-1",
                request=CapacityRequest("2026-08-09", 5),
            )

    def test_one_night_doctor_per_day(self) -> None:
        result = self.night_agent.run(
            requester_user_id="assistant-1",
            request=NightShiftRequest("2026-08-07", "doctor-1"),
        )
        self.assertEqual(result.doctor_display_name, "李医生")
        with self.assertRaises(AppointmentConflictError):
            self.night_agent.run(
                requester_user_id="assistant-1",
                request=NightShiftRequest("2026-08-07", "doctor-2"),
            )


if __name__ == "__main__":
    unittest.main()
