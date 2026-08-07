from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.agents.login_agent import LoginAgent
from app.core.identifiers import IdentifierProtector
from app.core.passwords import PasswordHasher
from app.db.connection import SQLiteConnectionFactory
from app.repositories.login_repository import LoginRepository
from app.schemas.login import IdentityType, LoginRequest
from app.services.login_service import LoginService
from scripts.bootstrap_accounts import bootstrap_accounts
from scripts.create_assistant_accounts import create_assistant_accounts


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class AssistantAccountTests(unittest.TestCase):
    def test_two_assistants_and_three_roles_login_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "test.db"
            pepper = root / "pepper.key"
            initial_csv = root / "initial.csv"
            assistant_csv = root / "assistants.csv"
            connection = sqlite3.connect(database)
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.close()
            bootstrap_accounts(
                database_path=database,
                credentials_path=initial_csv,
                pepper_path=pepper,
                password_iterations=1_000,
                required_drive=None,
            )
            create_assistant_accounts(
                database_path=database,
                pepper_path=pepper,
                credentials_path=assistant_csv,
                password_iterations=1_000,
                required_drive=None,
            )

            with initial_csv.open(encoding="utf-8-sig", newline="") as handle:
                initial = list(csv.DictReader(handle))
            with assistant_csv.open(encoding="utf-8-sig", newline="") as handle:
                assistants = list(csv.DictReader(handle))
            self.assertEqual(len(assistants), 2)

            protector = IdentifierProtector(pepper.read_bytes())
            agent = LoginAgent(
                LoginService(
                    LoginRepository(SQLiteConnectionFactory(database)),
                    PasswordHasher(iterations=1_000),
                    protector,
                )
            )
            patient = next(row for row in initial if row["role"] == "patient")
            doctor = next(row for row in initial if row["role"] == "doctor")
            assistant = assistants[0]
            requests = [
                LoginRequest(IdentityType.PATIENT, patient["account"], patient["initial_password"]),
                LoginRequest(IdentityType.DOCTOR, doctor["phone"], doctor["initial_password"]),
                LoginRequest(IdentityType.ASSISTANT, assistant["email"], assistant["initial_password"]),
            ]
            with ThreadPoolExecutor(max_workers=3) as executor:
                responses = list(executor.map(agent.run, requests))
            self.assertTrue(all(response.success for response in responses))
            self.assertEqual(
                {response.redirect_path for response in responses},
                {"patient/index.html", "doctor/index.html", "assistant/index.html"},
            )
            self.assertEqual(len({response.session_token for response in responses}), 3)


if __name__ == "__main__":
    unittest.main()
