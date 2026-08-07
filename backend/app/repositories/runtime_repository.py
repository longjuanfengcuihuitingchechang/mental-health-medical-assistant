from __future__ import annotations

from datetime import UTC, datetime

from app.db.connection import SQLiteConnectionFactory


class RuntimeRepository:
    def __init__(self, factory: SQLiteConnectionFactory):
        self.factory = factory

    def readiness(self) -> int:
        with self.factory.connect() as connection:
            version = connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0]
            connection.execute("SELECT 1").fetchone()
        return int(version)

    def get_session(self, token_hash: str) -> dict | None:
        with self.factory.connect() as connection:
            row = connection.execute(
                """SELECT s.id AS session_id,s.csrf_token_hash,s.expires_at,s.revoked_at,
                          u.id AS user_id,u.account,u.role,u.display_name,u.account_status,u.must_change_password
                   FROM user_sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? LIMIT 1""",
                (token_hash,),
            ).fetchone()
        return dict(row) if row else None

    def rotate_csrf(self, session_id: str, csrf_hash: str) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                "UPDATE user_sessions SET csrf_token_hash=?,last_seen_at=? WHERE id=?",
                (csrf_hash, datetime.now(UTC).isoformat(), session_id),
            )

    def revoke_session(self, session_id: str) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), session_id),
            )
