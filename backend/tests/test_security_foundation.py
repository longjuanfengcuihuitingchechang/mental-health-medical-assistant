from __future__ import annotations

import io
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.access_control import Permission, require_permission
from app.core.config import Settings
from app.core.errors import APIError
from app.core.passwords import PasswordHasher
from app.core.security_logging import SensitiveDataFilter, redact_log_text
from app.main import create_app


SCHEMA = Path(__file__).parents[1] / "db" / "schema.sql"
PROJECT_ROOT = Path(__file__).parents[2]


class SecurityFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = root / "security.db"
        self.pepper = root / "pepper.key"
        self.pepper.write_bytes(b"s" * 32)
        connection = sqlite3.connect(self.database)
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        connection.execute(
            """INSERT INTO users (id,account,password_hash,display_name,role)
               VALUES ('patient-sec','P980',?,'安全测试患者','patient')""",
            (PasswordHasher().hash_password("ValidPassword!1"),),
        )
        connection.execute(
            """INSERT INTO person_profiles (
                   user_id,id_card_fingerprint,id_card_masked,phone_masked,email_masked,
                   birth_date,gender,created_at,updated_at
               ) VALUES ('patient-sec','sec-fp','********1234','138****0000','s***@test.local',
                         '1990-01-01','unknown','2026-08-07T00:00:00+00:00','2026-08-07T00:00:00+00:00')"""
        )
        connection.commit()
        connection.close()
        self.settings = Settings(
            database_path=self.database,
            required_drive=None,
            auth_pepper_file=self.pepper,
            dotenv_file=root / ".env",
        )
        self.client = TestClient(create_app(self.settings))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def login(self, client=None):
        target = client or self.client
        return target.post(
            "/api/v1/auth/login",
            json={"identity_type": "patient", "account": "P980", "password": "ValidPassword!1"},
        )

    def test_rbac_matrix_denies_cross_role_permission(self):
        require_permission({"role": "patient"}, Permission.PATIENT_SELF)
        with self.assertRaises(APIError):
            require_permission({"role": "patient"}, Permission.DIRECTORY_READ)
        require_permission({"role": "super_admin"}, Permission.DIRECTORY_READ)

    def test_origin_body_cookie_and_security_headers(self):
        denied = self.client.get(
            "/api/v1/health/live",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["data"]["error"], "ORIGIN_DENIED")
        bad_host = self.client.get(
            "/api/v1/health/live",
            headers={"Host": "evil.example"},
        )
        self.assertEqual(bad_host.status_code, 400)
        oversized = self.client.post(
            "/api/v1/registrations",
            content=b"x" * (self.settings.max_request_body_bytes + 1),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(oversized.status_code, 413)
        login = self.login()
        cookie = login.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("secure", cookie)
        self.assertEqual(login.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", login.headers["content-security-policy"])

    def test_production_requires_secure_cookie_and_explicit_cors(self):
        with self.assertRaises(ValueError):
            Settings(
                database_path=self.database,
                required_drive=None,
                auth_pepper_file=self.pepper,
                app_env="production",
                session_cookie_secure=False,
            ).validate_security()

        production = Settings(
            database_path=self.database,
            required_drive=None,
            auth_pepper_file=self.pepper,
            app_env="production",
            session_cookie_secure=True,
        )
        with TestClient(create_app(production)) as client:
            response = client.get("/api/v1/health/live")
            self.assertNotIn("cdn.tailwindcss.com", response.headers["content-security-policy"])
            self.assertNotIn("unsafe-inline", response.headers["content-security-policy"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/docs").status_code, 404)
        with self.assertRaises(ValueError):
            Settings(
                database_path=self.database,
                required_drive=None,
                auth_pepper_file=self.pepper,
                allowed_hosts_raw="*",
            ).validate_security()
        with self.assertRaises(ValueError):
            Settings(
                database_path=self.database,
                required_drive=None,
                auth_pepper_file=self.pepper,
                cors_allowed_origins_raw="*",
            ).validate_security()

    def test_csrf_denial_is_audited(self):
        self.login()
        denied = self.client.post("/api/v1/auth/logout")
        self.assertEqual(denied.status_code, 403)
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT action,error_code,request_id FROM audit_events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], "security.request_denied")
        self.assertEqual(row[1], "CSRF_FAILED")
        self.assertTrue(row[2].startswith("req_"))

    def test_login_and_assistant_rate_limits_return_429(self):
        low = Settings(
            database_path=self.database,
            required_drive=None,
            auth_pepper_file=self.pepper,
            dotenv_file=Path(self.temp.name) / ".env",
            login_account_limit=1,
            login_ip_limit=10,
            assistant_user_limit=1,
        )
        with TestClient(create_app(low)) as client:
            first = self.login(client)
            self.assertEqual(first.status_code, 200)
            second = self.login(client)
            self.assertEqual(second.status_code, 429)
            self.assertGreaterEqual(int(second.headers["retry-after"]), 1)
            csrf = first.json()["data"]["csrf_token"]
            payload = {"page": "overview", "feature_key": "page", "event": "page_open", "message": ""}
            allowed = client.post(
                "/api/v1/patient/page-assistant/respond",
                headers={"X-CSRF-Token": csrf},
                json=payload,
            )
            self.assertEqual(allowed.status_code, 200)
            limited = client.post(
                "/api/v1/patient/page-assistant/respond",
                headers={"X-CSRF-Token": csrf},
                json=payload,
            )
            self.assertEqual(limited.status_code, 429)
        connection = sqlite3.connect(self.database)
        try:
            errors = [row[0] for row in connection.execute("SELECT error_code FROM audit_events WHERE action='security.request_denied'")]
        finally:
            connection.close()
        self.assertIn("RATE_LIMITED", errors)

    def test_audit_is_append_only(self):
        self.client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
        connection = sqlite3.connect(self.database)
        try:
            audit_id = connection.execute("SELECT id FROM audit_events LIMIT 1").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET status='success' WHERE id=?", (audit_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM audit_events WHERE id=?", (audit_id,))
        finally:
            connection.close()

    def test_log_redaction_and_frontend_secret_boundary(self):
        source = "password=Open123 token=abc Bearer xyz user@example.com 13812345678 11010519491231002X"
        redacted = redact_log_text(source)
        for secret in ("Open123", "abc", "xyz", "user@example.com", "13812345678", "11010519491231002X"):
            self.assertNotIn(secret, redacted)
        logger = logging.getLogger("security-test")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.handlers = [handler]
        logger.filters = [SensitiveDataFilter()]
        logger.setLevel(logging.INFO)
        logger.info("api_key=top-secret")
        self.assertNotIn("top-secret", stream.getvalue())
        frontend = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (PROJECT_ROOT / "fronts").rglob("*")
            if path.is_file()
        )
        for marker in ("DEEPSEEK_API_KEY", "AUTH_PEPPER_FILE", "initial_password", "BEGIN " + "PRIVATE KEY"):
            self.assertNotIn(marker, frontend)


if __name__ == "__main__":
    unittest.main()
