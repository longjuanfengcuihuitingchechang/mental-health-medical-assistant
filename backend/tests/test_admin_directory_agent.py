from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.agents.admin_directory_agent import AdminDirectoryAgent
from app.db.connection import SQLiteConnectionFactory
from app.repositories.admin_directory_repository import AdminDirectoryRepository
from app.schemas.admin_directory import (
    AccountStatus,
    AdminDirectoryRequest,
    DirectoryPermissionError,
    DirectoryTarget,
    EmploymentStatus,
)
from app.services.admin_directory_service import AdminDirectoryService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class AdminDirectoryAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.executemany(
            """
            INSERT INTO users (
                id, account, password_hash, display_name, role,
                account_status, blacklisted
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("super-1", "root_admin", "secret-hash", "最高管理员", "super_admin", "active", 0),
                ("admin-1", "admin_a", "secret-hash", "普通管理员", "admin", "active", 0),
                ("doctor-1", "doctor_a", "secret-hash", "张医生", "doctor", "active", 0),
                ("doctor-2", "doctor_b", "secret-hash", "李医生", "doctor", "disabled", 0),
                ("assistant-1", "assistant_a", "secret-hash", "协调助理", "assistant", "active", 0),
                ("patient-1", "patient_a", "secret-hash", "患者甲", "patient", "active", 1),
            ],
        )
        connection.execute(
            """INSERT INTO assistant_profiles(
                user_id, employee_no, employment_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)""",
            ("assistant-1", "S001", "active", "2026-08-06", "2026-08-06"),
        )
        connection.execute(
            "INSERT INTO admin_profiles(user_id, employee_no, department) VALUES (?, ?, ?)",
            ("super-1", "A000", "系统管理"),
        )
        connection.execute(
            "INSERT INTO admin_profiles(user_id, employee_no, department) VALUES (?, ?, ?)",
            ("admin-1", "A001", "运营管理"),
        )
        connection.execute(
            """INSERT INTO doctor_profiles(
                user_id, employee_no, department, professional_title, employment_status
            ) VALUES (?, ?, ?, ?, ?)""",
            ("doctor-1", "D001", "心理科", "主治医师", "active"),
        )
        connection.execute(
            """INSERT INTO doctor_profiles(
                user_id, employee_no, department, professional_title, employment_status
            ) VALUES (?, ?, ?, ?, ?)""",
            ("doctor-2", "D002", "心理科", "医师", "resigned"),
        )
        connection.execute(
            """INSERT INTO patient_profiles(
                user_id, medical_record_no, assigned_doctor_user_id
            ) VALUES (?, ?, ?)""",
            ("patient-1", "P001", "doctor-1"),
        )
        connection.commit()
        connection.close()

        repository = AdminDirectoryRepository(
            SQLiteConnectionFactory(self.database_path)
        )
        self.agent = AdminDirectoryAgent(AdminDirectoryService(repository))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_admin_can_list_patients_without_sensitive_fields(self) -> None:
        result = self.agent.run(
            requester_user_id="admin-1",
            request=AdminDirectoryRequest(
                target_role=DirectoryTarget.PATIENT,
                blacklisted=True,
            ),
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["account"], "patient_a")
        self.assertNotIn("password_hash", result.items[0])

    def test_admin_can_filter_active_doctors(self) -> None:
        result = self.agent.run(
            requester_user_id="admin-1",
            request=AdminDirectoryRequest(
                target_role=DirectoryTarget.DOCTOR,
                account_status=AccountStatus.ACTIVE,
                employment_status=EmploymentStatus.ACTIVE,
            ),
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["employee_no"], "D001")

    def test_admin_cannot_list_admins(self) -> None:
        with self.assertRaises(DirectoryPermissionError):
            self.agent.run(
                requester_user_id="admin-1",
                request=AdminDirectoryRequest(target_role=DirectoryTarget.ADMIN),
            )

    def test_admin_can_list_assistants(self) -> None:
        result = self.agent.run(
            requester_user_id="admin-1",
            request=AdminDirectoryRequest(
                target_role=DirectoryTarget.ASSISTANT,
                employment_status=EmploymentStatus.ACTIVE,
            ),
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["employee_no"], "S001")

    def test_super_admin_can_list_admins(self) -> None:
        result = self.agent.run(
            requester_user_id="super-1",
            request=AdminDirectoryRequest(target_role=DirectoryTarget.ADMIN),
        )
        self.assertEqual(result.total, 2)
        self.assertEqual({item["role"] for item in result.items}, {"admin", "super_admin"})
        self.assertTrue(all("password_hash" not in item for item in result.items))

    def test_non_admin_cannot_use_agent(self) -> None:
        with self.assertRaises(DirectoryPermissionError):
            self.agent.run(
                requester_user_id="patient-1",
                request=AdminDirectoryRequest(target_role=DirectoryTarget.PATIENT),
            )

    def test_every_attempt_is_audited(self) -> None:
        with self.assertRaises(DirectoryPermissionError):
            self.agent.run(
                requester_user_id="admin-1",
                request=AdminDirectoryRequest(target_role=DirectoryTarget.ADMIN),
            )
        connection = sqlite3.connect(self.database_path)
        status = connection.execute(
            "SELECT status FROM audit_events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(status, "denied")


if __name__ == "__main__":
    unittest.main()
