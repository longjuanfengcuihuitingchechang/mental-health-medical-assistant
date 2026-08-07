from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.passwords import PasswordHasher
from app.main import create_app


class HTTPFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = root / "test.db"
        self.pepper = root / "pepper.key"
        self.pepper.write_bytes(b"x" * 32)
        schema = Path(__file__).parents[1] / "db" / "schema.sql"
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(schema.read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT INTO users (
                    id, account, password_hash, display_name, role
                ) VALUES (?, ?, ?, ?, 'patient')
                """,
                (
                    "patient-http",
                    "P900",
                    PasswordHasher().hash_password("ValidPassword!1"),
                    "HTTP 测试患者",
                ),
            )
            connection.execute(
                "INSERT INTO users (id,account,password_hash,display_name,role) VALUES (?, ?, ?, ?, 'doctor')",
                ("doctor-http", "D900", PasswordHasher().hash_password("ValidPassword!1"), "HTTP 测试医生"),
            )
            connection.execute(
                """INSERT INTO person_profiles (
                       user_id,id_card_fingerprint,id_card_masked,phone_masked,
                       email_masked,birth_date,gender,created_at,updated_at
                   ) VALUES ('patient-http','http-fp','********1234','138****0000',
                             'h***@example.test','1990-01-01','unknown',
                             '2026-08-07T00:00:00+00:00','2026-08-07T00:00:00+00:00')"""
            )
            connection.execute(
                "INSERT INTO doctor_profiles (user_id,employee_no,employment_status) VALUES ('doctor-http','D900','active')"
            )
            connection.commit()
        finally:
            connection.close()
        app = create_app(
            Settings(
                database_path=self.database,
                required_drive=None,
                auth_pepper_file=self.pepper,
                dotenv_file=root / ".env",
            )
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_health_login_session_and_logout(self) -> None:
        live = self.client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertTrue(live.headers["x-request-id"].startswith("req_"))

        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.json()["data"]["schema_version"], 9)

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "identity_type": "patient",
                "account": "P900",
                "password": "ValidPassword!1",
            },
        )
        self.assertEqual(login.status_code, 200)
        csrf = login.json()["data"]["csrf_token"]
        self.assertNotIn("session_token", login.text)

        session = self.client.get("/api/v1/auth/session")
        self.assertEqual(session.json()["data"]["account"], "P900")
        csrf = session.json()["data"]["csrf_token"]

        denied = self.client.post("/api/v1/auth/logout")
        self.assertEqual(denied.status_code, 403)
        logout = self.client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/auth/session").status_code,
            401,
        )

    def test_frontend_and_api_are_same_origin(self) -> None:
        frontend = self.client.get("/index.html")
        self.assertEqual(frontend.status_code, 200)
        self.assertIn("shared/api.js", frontend.text)
        self.assertEqual(self.client.get("/api/v1/health/live").status_code, 200)

    def test_invalid_login_uses_stable_error(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "identity_type": "patient",
                "account": "P900",
                "password": "wrong",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["data"]["error"], "INVALID_CREDENTIALS")

    def test_v1_domain_routes_are_exposed(self) -> None:
        paths = self.client.app.openapi()["paths"]
        expected = {
            "/api/v1/registrations",
            "/api/v1/admin/doctor-registrations/{registration_request_id}/decision",
            "/api/v1/admin/directory/{target_role}",
            "/api/v1/patient/page-assistant/respond",
            "/api/v1/patient/page-assistant/tasks",
            "/api/v1/patient/page-assistant/sessions/{assistant_session_id}/messages",
            "/api/v1/doctors/me/capacities/{appointment_date}",
            "/api/v1/patient/appointments",
            "/api/v1/patient/appointments/{appointment_id}/decision",
            "/api/v1/doctors/me/appointments/pending-decisions",
            "/api/v1/assistants/me/coordination-queue",
            "/api/v1/doctors/me/appointments/{appointment_id}/decision",
            "/api/v1/night-shifts/{shift_date}",
            "/api/v1/{role}/work-assistant/respond",
            "/api/v1/{role}/work-assistant/tasks",
            "/api/v1/agent-tasks/{task_id}",
            "/api/v1/agent-tasks/{task_id}/events",
            "/api/v1/agent-tasks/{task_id}/cancel",
        }
        self.assertTrue(expected.issubset(paths))

    def test_doctor_work_assistant_uses_authenticated_role(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login",
            json={"identity_type": "doctor", "account": "D900", "password": "ValidPassword!1"},
        )
        csrf = login.json()["data"]["csrf_token"]
        denied = self.client.post(
            "/api/v1/assistant/work-assistant/respond",
            headers={"X-CSRF-Token": csrf},
            json={"page": "schedule", "feature_key": "daily", "message": "查询我的排班"},
        )
        self.assertEqual(denied.status_code, 403)
        response = self.client.post(
            "/api/v1/doctor/work-assistant/respond",
            headers={"X-CSRF-Token": csrf},
            json={"page": "schedule", "feature_key": "daily", "message": "查询我的排班"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["tool_calls"][0]["tool_name"], "get_my_schedule")

    def test_patient_async_task_stream_and_crisis_short_circuit(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login",
            json={"identity_type": "patient", "account": "P900", "password": "ValidPassword!1"},
        )
        csrf = login.json()["data"]["csrf_token"]
        crisis = self.client.post(
            "/api/v1/patient/page-assistant/tasks",
            headers={"X-CSRF-Token": csrf},
            json={
                "page": "support",
                "feature_key": "ask_question",
                "event": "message",
                "message": "我不想活了",
            },
        )
        self.assertEqual(crisis.status_code, 200)
        self.assertTrue(crisis.json()["data"]["crisis"])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM async_tasks").fetchone()[0], 0)
        finally:
            connection.close()

        created = self.client.post(
            "/api/v1/patient/page-assistant/tasks",
            headers={"X-CSRF-Token": csrf},
            json={
                "page": "support",
                "feature_key": "ask_question",
                "event": "message",
                "message": "这个页面如何使用？",
            },
        )
        self.assertEqual(created.status_code, 202)
        task = created.json()["data"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = self.client.get(f"/api/v1/agent-tasks/{task['task_id']}").json()["data"]
            if snapshot["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.01)
        self.assertEqual(snapshot["status"], "SUCCEEDED")
        stream = self.client.get(task["stream_url"])
        self.assertEqual(stream.status_code, 200)
        self.assertIn("event: task.created", stream.text)
        self.assertIn("event: message.delta", stream.text)
        self.assertIn("event: task.completed", stream.text)
        resumed = self.client.get(task["stream_url"], headers={"Last-Event-ID": "2"})
        self.assertNotIn("event: task.created", resumed.text)


if __name__ == "__main__":
    unittest.main()
