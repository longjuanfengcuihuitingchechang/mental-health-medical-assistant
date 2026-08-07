from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.bootstrap_accounts import bootstrap_accounts


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "db" / "schema.sql"


class BootstrapAccountsTests(unittest.TestCase):
    def test_bootstrap_creates_exact_counts_and_private_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "test.db"
            credentials_path = root / "private" / "initial_accounts.csv"
            pepper_path = root / "private" / "auth_pepper.key"
            connection = sqlite3.connect(database_path)
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.close()

            result = bootstrap_accounts(
                database_path=database_path,
                credentials_path=credentials_path,
                pepper_path=pepper_path,
                password_iterations=1_000,
                required_drive=None,
            )
            self.assertEqual(result["counts"]["patient"], 50)

            connection = sqlite3.connect(database_path)
            counts = dict(
                connection.execute(
                    "SELECT role, COUNT(*) FROM users GROUP BY role"
                ).fetchall()
            )
            plaintext_columns = connection.execute(
                "SELECT phone_masked, email_masked, id_card_masked FROM person_profiles"
            ).fetchall()
            sequences = dict(
                connection.execute(
                    "SELECT prefix, next_value FROM account_sequences"
                ).fetchall()
            )
            connection.close()

            self.assertEqual(
                counts,
                {"admin": 2, "doctor": 5, "patient": 50, "super_admin": 1},
            )
            self.assertEqual(sequences, {"A": 4, "D": 6, "P": 51, "S": 1})
            self.assertTrue(all("****" in row[0] for row in plaintext_columns))
            self.assertTrue(all("***@" in row[1] for row in plaintext_columns))
            self.assertTrue(all("********" in row[2] for row in plaintext_columns))

            with credentials_path.open(encoding="utf-8-sig", newline="") as handle:
                credentials = list(csv.DictReader(handle))
            self.assertEqual(len(credentials), 58)
            self.assertEqual(credentials[0]["account"], "A001")
            self.assertEqual(credentials[-1]["account"], "P050")
            self.assertTrue(all(row["initial_password"] for row in credentials))
            self.assertEqual(len(pepper_path.read_bytes()), 32)


if __name__ == "__main__":
    unittest.main()
