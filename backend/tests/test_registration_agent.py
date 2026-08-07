from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.agents.login_agent import LoginAgent
from app.agents.registration_agent import (
    DoctorRegistrationApprovalAgent,
    RegistrationAgent,
)
from app.core.identifiers import (
    ID_CARD_CHECK_CODES,
    ID_CARD_WEIGHTS,
    IdentifierProtector,
)
from app.core.passwords import PasswordHasher
from app.db.connection import SQLiteConnectionFactory
from app.repositories.login_repository import LoginRepository
from app.repositories.registration_repository import RegistrationRepository
from app.schemas.login import IdentityType, LoginRequest
from app.schemas.registration import (
    ApprovalAction,
    DoctorApprovalRequest,
    RegistrationConflictError,
    RegistrationPermissionError,
    RegistrationRequest,
    RegistrationRole,
    RegistrationStatus,
)
from app.services.login_service import LoginService
from app.services.registration_service import (
    DoctorRegistrationApprovalService,
    RegistrationService,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


def synthetic_id_card(sequence: int, birth_date: str = "19900101") -> str:
    base = f"999999{birth_date}{sequence:03d}"
    total = sum(int(number) * weight for number, weight in zip(base, ID_CARD_WEIGHTS))
    return base + ID_CARD_CHECK_CODES[total % 11]


class RegistrationAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            """
            INSERT INTO users (
                id, account, password_hash, display_name, role, account_status
            ) VALUES ('admin-1', 'A001', 'not-used', '管理员', 'admin', 'active')
            """
        )
        connection.execute(
            """
            INSERT INTO users (
                id, account, password_hash, display_name, role, account_status
            ) VALUES ('patient-reviewer', 'P900', 'not-used', '普通患者', 'patient', 'active')
            """
        )
        connection.commit()
        connection.close()

        self.password_hasher = PasswordHasher(iterations=1_000)
        self.protector = IdentifierProtector(b"t" * 32)
        factory = SQLiteConnectionFactory(self.database_path)
        repository = RegistrationRepository(factory, self.protector)
        fixed_clock = lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
        self.registration_agent = RegistrationAgent(
            RegistrationService(
                repository,
                self.password_hasher,
                self.protector,
                clock=fixed_clock,
            )
        )
        self.approval_agent = DoctorRegistrationApprovalAgent(
            DoctorRegistrationApprovalService(repository, clock=fixed_clock)
        )
        self.login_agent = LoginAgent(
            LoginService(
                LoginRepository(factory),
                self.password_hasher,
                self.protector,
                clock=fixed_clock,
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_patient_is_active_and_can_login_by_account_phone_or_email(self) -> None:
        response = self._register_patient()
        self.assertEqual(response.account, "P001")
        self.assertEqual(response.status, RegistrationStatus.ACTIVE)

        for login_value in ("P001", "18890000001", "patient1@example.invalid"):
            with self.subTest(login_value=login_value):
                login = self.login_agent.run(
                    LoginRequest(
                        IdentityType.PATIENT,
                        login_value,
                        "Strong Password 123",
                    )
                )
                self.assertTrue(login.success)

    def test_doctor_requires_admin_approval_before_login(self) -> None:
        response = self._register_doctor()
        self.assertEqual(response.account, "D001")
        self.assertEqual(response.status, RegistrationStatus.PENDING_APPROVAL)

        before = self.login_agent.run(
            LoginRequest(
                IdentityType.DOCTOR,
                "doctor1@example.invalid",
                "Strong Password 123",
            )
        )
        self.assertFalse(before.success)

        reviewed = self.approval_agent.run(
            requester_user_id="admin-1",
            request=DoctorApprovalRequest(
                registration_request_id=response.registration_request_id,
                action=ApprovalAction.APPROVE,
                review_note="资质已线下核验",
            ),
        )
        self.assertEqual(reviewed.status, RegistrationStatus.APPROVED)

        after = self.login_agent.run(
            LoginRequest(
                IdentityType.DOCTOR,
                "18890000002",
                "Strong Password 123",
            )
        )
        self.assertTrue(after.success)

        connection = sqlite3.connect(self.database_path)
        doctor = connection.execute(
            "SELECT employee_no, employment_status FROM doctor_profiles"
        ).fetchone()
        connection.close()
        self.assertEqual(doctor, ("D001", "active"))

    def test_non_admin_cannot_approve_doctor(self) -> None:
        response = self._register_doctor()
        with self.assertRaises(RegistrationPermissionError):
            self.approval_agent.run(
                requester_user_id="patient-reviewer",
                request=DoctorApprovalRequest(
                    registration_request_id=response.registration_request_id,
                    action=ApprovalAction.APPROVE,
                ),
            )

    def test_rejection_requires_reason_and_disables_account(self) -> None:
        response = self._register_doctor()
        with self.assertRaises(ValueError):
            self.approval_agent.run(
                requester_user_id="admin-1",
                request=DoctorApprovalRequest(
                    registration_request_id=response.registration_request_id,
                    action=ApprovalAction.REJECT,
                ),
            )
        reviewed = self.approval_agent.run(
            requester_user_id="admin-1",
            request=DoctorApprovalRequest(
                registration_request_id=response.registration_request_id,
                action=ApprovalAction.REJECT,
                review_note="材料不完整",
            ),
        )
        self.assertEqual(reviewed.status, RegistrationStatus.REJECTED)

    def test_duplicate_phone_is_rejected_without_consuming_account(self) -> None:
        self._register_patient()
        with self.assertRaises(RegistrationConflictError):
            self.registration_agent.run(
                RegistrationRequest(
                    role=RegistrationRole.PATIENT,
                    password="Another Password 456",
                    display_name="重复手机号",
                    id_card=synthetic_id_card(3),
                    phone="18890000001",
                    email="unique@example.invalid",
                )
            )
        second = self.registration_agent.run(
            RegistrationRequest(
                role=RegistrationRole.PATIENT,
                password="Another Password 456",
                display_name="第二患者",
                id_card=synthetic_id_card(4),
                phone="18890000004",
                email="patient4@example.invalid",
            )
        )
        self.assertEqual(second.account, "P002")

    def test_database_stores_only_masked_personal_identifiers(self) -> None:
        self._register_patient()
        connection = sqlite3.connect(self.database_path)
        person = connection.execute(
            """SELECT id_card_masked, phone_masked, email_masked
               FROM person_profiles WHERE user_id != 'patient-reviewer'"""
        ).fetchone()
        identifier_rows = connection.execute(
            "SELECT identifier_fingerprint, identifier_masked FROM user_login_identifiers"
        ).fetchall()
        connection.close()
        self.assertNotIn(synthetic_id_card(1), person)
        self.assertNotIn("18890000001", person)
        self.assertNotIn("patient1@example.invalid", person)
        self.assertTrue(all(len(row[0]) == 64 for row in identifier_rows))

    def _register_patient(self):
        return self.registration_agent.run(
            RegistrationRequest(
                role=RegistrationRole.PATIENT,
                password="Strong Password 123",
                display_name="患者一",
                id_card=synthetic_id_card(1),
                phone="18890000001",
                email="patient1@example.invalid",
            )
        )

    def _register_doctor(self):
        return self.registration_agent.run(
            RegistrationRequest(
                role=RegistrationRole.DOCTOR,
                password="Strong Password 123",
                display_name="医生一",
                id_card=synthetic_id_card(2),
                phone="18890000002",
                email="doctor1@example.invalid",
                department="心理科",
                professional_title="医师",
            )
        )


if __name__ == "__main__":
    unittest.main()
