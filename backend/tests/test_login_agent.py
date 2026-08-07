from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agents.login_agent import LoginAgent
from app.core.passwords import PasswordHasher
from app.core.identifiers import IdentifierProtector
from app.db.connection import SQLiteConnectionFactory
from app.repositories.login_repository import LoginRepository
from app.schemas.admin_directory import UserRole
from app.schemas.login import IdentityType, LoginErrorCode, LoginRequest
from app.services.login_service import LoginService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 6, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


class LoginAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.password_hasher = PasswordHasher(iterations=1_000)
        self.identifier_protector = IdentifierProtector(b"l" * 32)
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        users = [
            ("patient-1", "patient_a", "患者甲", "patient", "active"),
            ("doctor-1", "doctor_a", "张医生", "doctor", "active"),
            ("admin-1", "admin_a", "普通管理员", "admin", "active"),
            ("super-1", "root_admin", "最高管理员", "super_admin", "active"),
            ("disabled-1", "disabled_user", "停用患者", "patient", "disabled"),
        ]
        connection.executemany(
            """
            INSERT INTO users (
                id, account, password_hash, display_name, role, account_status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    account,
                    self.password_hasher.hash_password("Correct Password 123"),
                    display_name,
                    role,
                    status,
                )
                for user_id, account, display_name, role, status in users
            ],
        )
        connection.commit()
        connection.close()

        self.clock = FakeClock()
        repository = LoginRepository(SQLiteConnectionFactory(self.database_path))
        self.agent = LoginAgent(
            LoginService(
                repository,
                self.password_hasher,
                self.identifier_protector,
                clock=self.clock,
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_each_identity_redirects_to_its_interface(self) -> None:
        cases = [
            (IdentityType.PATIENT, "patient_a", UserRole.PATIENT, "patient/index.html"),
            (IdentityType.DOCTOR, "doctor_a", UserRole.DOCTOR, "doctor/index.html"),
            (IdentityType.ADMIN, "admin_a", UserRole.ADMIN, "admin/index.html"),
            (IdentityType.ADMIN, "root_admin", UserRole.SUPER_ADMIN, "admin/index.html"),
        ]
        for identity, account, role, redirect in cases:
            with self.subTest(account=account):
                response = self.agent.run(
                    LoginRequest(identity, account, "Correct Password 123")
                )
                self.assertTrue(response.success)
                self.assertEqual(response.role, role)
                self.assertEqual(response.redirect_path, redirect)
                self.assertIsNotNone(response.session_token)

    def test_identity_mismatch_uses_generic_error(self) -> None:
        response = self.agent.run(
            LoginRequest(IdentityType.DOCTOR, "patient_a", "Correct Password 123")
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error_code, LoginErrorCode.INVALID_CREDENTIALS)
        self.assertIn("账号、密码或身份类型不匹配", response.message)

    def test_seventh_warns_and_eighth_locks_for_five_minutes(self) -> None:
        request = LoginRequest(IdentityType.PATIENT, "patient_a", "wrong password")
        for _ in range(6):
            response = self.agent.run(request)
            self.assertEqual(response.error_code, LoginErrorCode.INVALID_CREDENTIALS)

        seventh = self.agent.run(request)
        self.assertEqual(seventh.error_code, LoginErrorCode.LOCK_WARNING)
        self.assertEqual(seventh.remaining_attempts, 1)
        self.assertIn("再失败 1 次", seventh.message)

        eighth = self.agent.run(request)
        self.assertEqual(eighth.error_code, LoginErrorCode.TEMPORARILY_LOCKED)
        self.assertEqual(eighth.locked_remaining_seconds, 300)
        self.assertIn("锁定 5 分钟", eighth.message)

        locked = self.agent.run(
            LoginRequest(
                IdentityType.PATIENT,
                "patient_a",
                "Correct Password 123",
            )
        )
        self.assertFalse(locked.success)
        self.assertEqual(locked.error_code, LoginErrorCode.TEMPORARILY_LOCKED)

        self.clock.advance(minutes=5, seconds=1)
        unlocked = self.agent.run(
            LoginRequest(
                IdentityType.PATIENT,
                "patient_a",
                "Correct Password 123",
            )
        )
        self.assertTrue(unlocked.success)

    def test_success_resets_failure_count(self) -> None:
        wrong = LoginRequest(IdentityType.PATIENT, "patient_a", "wrong")
        for _ in range(6):
            self.agent.run(wrong)
        success = self.agent.run(
            LoginRequest(
                IdentityType.PATIENT,
                "patient_a",
                "Correct Password 123",
            )
        )
        self.assertTrue(success.success)
        next_failure = self.agent.run(wrong)
        self.assertEqual(next_failure.error_code, LoginErrorCode.INVALID_CREDENTIALS)
        self.assertIsNone(next_failure.remaining_attempts)

    def test_disabled_account_uses_generic_error(self) -> None:
        response = self.agent.run(
            LoginRequest(
                IdentityType.PATIENT,
                "disabled_user",
                "Correct Password 123",
            )
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error_code, LoginErrorCode.INVALID_CREDENTIALS)

    def test_session_database_stores_only_token_hash(self) -> None:
        response = self.agent.run(
            LoginRequest(
                IdentityType.PATIENT,
                "PATIENT_A",
                "Correct Password 123",
            )
        )
        self.assertTrue(response.success)
        connection = sqlite3.connect(self.database_path)
        stored_hash = connection.execute(
            "SELECT token_hash FROM user_sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        audit_filters = connection.execute(
            "SELECT filters_json FROM audit_events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(
            stored_hash,
            hashlib.sha256(response.session_token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(stored_hash, response.session_token)
        self.assertNotIn("Correct Password 123", audit_filters)
        self.assertNotIn(response.session_token, audit_filters)


class PasswordHasherTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self) -> None:
        hasher = PasswordHasher(iterations=1_000)
        first = hasher.hash_password("测试 Password")
        second = hasher.hash_password("测试 Password")
        self.assertNotEqual(first, second)
        self.assertTrue(hasher.verify_password("测试 Password", first))
        self.assertFalse(hasher.verify_password("wrong", first))


if __name__ == "__main__":
    unittest.main()
