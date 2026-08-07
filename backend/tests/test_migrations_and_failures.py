from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.db.connection import SQLiteConnectionFactory
from app.repositories.security_repository import SecurityRepository


PROJECT_ROOT = Path(__file__).parents[2]
SCHEMA = PROJECT_ROOT / "backend" / "db" / "schema.sql"
MIGRATION_V9 = PROJECT_ROOT / "backend" / "db" / "migrations" / "009_security_hardening.sql"


class MigrationAndFailureTests(unittest.TestCase):
    def test_v9_scrubs_legacy_identifiers_before_append_only_triggers(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE schema_metadata (version INTEGER NOT NULL);
            INSERT INTO schema_metadata(version) VALUES (8);
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id TEXT,
                actor_role TEXT,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_user_id TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                filters_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO audit_events(action,target_type,status,filters_json)
            VALUES ('registration.submit','registration','success','{"account":"P001"}');
            INSERT INTO audit_events(action,target_type,status,filters_json)
            VALUES ('directory.list','user_directory','success','{"keyword":"synthetic"}');
            """
        )
        connection.executescript(MIGRATION_V9.read_text(encoding="utf-8"))

        self.assertEqual(
            connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0],
            9,
        )
        self.assertEqual(
            connection.execute("SELECT DISTINCT filters_json FROM audit_events").fetchall(),
            [("{}",)],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE audit_events SET status='failed'")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM audit_events")
        connection.close()

    def test_sqlite_rate_limit_is_atomic_under_concurrency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "rate-limit.db"
            connection = sqlite3.connect(database)
            connection.executescript(SCHEMA.read_text(encoding="utf-8"))
            connection.close()
            repository = SecurityRepository(SQLiteConnectionFactory(database))
            now = datetime(2026, 8, 7, tzinfo=UTC)

            def consume(_index: int):
                return repository.consume_rate_limit(
                    bucket_key="test:assistant:synthetic-user",
                    limit=5,
                    window_seconds=60,
                    now=now,
                )

            with ThreadPoolExecutor(max_workers=12) as executor:
                results = list(executor.map(consume, range(12)))

            self.assertEqual(sum(1 for allowed, _, _ in results if allowed), 5)
            self.assertEqual(sum(1 for allowed, _, _ in results if not allowed), 7)
            self.assertTrue(all(retry >= 1 for allowed, retry, _ in results if not allowed))
            connection = sqlite3.connect(database)
            row = connection.execute(
                "SELECT request_count,blocked_until FROM api_rate_limits WHERE bucket_key=?",
                ("test:assistant:synthetic-user",),
            ).fetchone()
            connection.close()
            self.assertEqual(row[0], 6)
            self.assertIsNotNone(row[1])

    def test_missing_database_parent_does_not_create_fallback_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            requested = Path(temp_dir) / "missing-drive" / "mental-health.db"
            factory = SQLiteConnectionFactory(requested)
            with self.assertRaises(sqlite3.OperationalError):
                with factory.connect():
                    pass
            self.assertFalse(requested.exists())
            self.assertFalse(requested.parent.exists())

            with self.assertRaises(ValueError):
                Settings(database_path=Path(temp_dir) / "wrong-drive.db", required_drive="E:").validated_database_path()


if __name__ == "__main__":
    unittest.main()
