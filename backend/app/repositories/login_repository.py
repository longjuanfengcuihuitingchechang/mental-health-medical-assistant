from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from app.db.connection import SQLiteConnectionFactory
from app.schemas.login import IdentityType


class LoginRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory):
        self.connection_factory = connection_factory

    def find_user(
        self,
        *,
        identity_type: IdentityType,
        account: str,
        identifier_fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        roles = (
            ("admin", "super_admin")
            if identity_type is IdentityType.ADMIN
            else (identity_type.value,)
        )
        placeholders = ", ".join("?" for _ in roles)
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                f"""
                SELECT id, account, password_hash, display_name, role,
                       account_status, must_change_password
                FROM users
                WHERE (
                    account = ? COLLATE NOCASE
                    OR EXISTS (
                        SELECT 1
                        FROM user_login_identifiers uli
                        WHERE uli.user_id = users.id
                          AND uli.identifier_fingerprint = ?
                    )
                )
                  AND role IN ({placeholders})
                LIMIT 1
                """,
                (account, identifier_fingerprint, *roles),
            ).fetchone()
        return dict(row) if row else None

    def get_security_state(self, account_fingerprint: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                """
                SELECT failed_attempts, locked_until
                FROM login_security_states
                WHERE account_fingerprint = ?
                """,
                (account_fingerprint,),
            ).fetchone()
        return dict(row) if row else None

    def register_failure(
        self,
        *,
        account_fingerprint: str,
        user_id: str | None,
        failed_at: datetime,
        max_attempts: int,
        locked_until: datetime,
    ) -> tuple[int, str | None]:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT failed_attempts
                    FROM login_security_states
                    WHERE account_fingerprint = ?
                    """,
                    (account_fingerprint,),
                ).fetchone()
                failed_attempts = (int(row[0]) if row else 0) + 1
                lock_value = (
                    locked_until.isoformat()
                    if failed_attempts >= max_attempts
                    else None
                )
                connection.execute(
                    """
                    INSERT INTO login_security_states (
                        account_fingerprint, user_id, failed_attempts,
                        locked_until, last_failed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_fingerprint) DO UPDATE SET
                        user_id = COALESCE(excluded.user_id, login_security_states.user_id),
                        failed_attempts = excluded.failed_attempts,
                        locked_until = excluded.locked_until,
                        last_failed_at = excluded.last_failed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        account_fingerprint,
                        user_id,
                        failed_attempts,
                        lock_value,
                        failed_at.isoformat(),
                        failed_at.isoformat(),
                    ),
                )
                connection.commit()
                return failed_attempts, lock_value
            except Exception:
                connection.rollback()
                raise

    def reset_security_state(self, account_fingerprint: str) -> None:
        with self.connection_factory.connect() as connection:
            connection.execute(
                "DELETE FROM login_security_states WHERE account_fingerprint = ?",
                (account_fingerprint,),
            )

    def create_session(
        self,
        *,
        session_id: str,
        token_hash: str,
        csrf_token_hash: str,
        user_id: str,
        created_at: datetime,
        expires_at: datetime,
        account_fingerprint: str,
    ) -> None:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO user_sessions (
                        id, token_hash, csrf_token_hash, user_id,
                        created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        token_hash,
                        csrf_token_hash,
                        user_id,
                        created_at.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                connection.execute(
                    "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                    (created_at.isoformat(), created_at.isoformat(), user_id),
                )
                connection.execute(
                    "DELETE FROM login_security_states WHERE account_fingerprint = ?",
                    (account_fingerprint,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def write_audit(
        self,
        *,
        actor_user_id: str | None,
        account_fingerprint: str,
        identity_type: IdentityType,
        status: str,
        error_code: str | None,
    ) -> None:
        with self.connection_factory.connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor_user_id, action, target_type,
                    filters_json, result_count, status, error_code
                ) VALUES (?, ?, 'auth.login', 'session', ?, 0, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    actor_user_id,
                    json.dumps(
                        {
                            "identity_type": identity_type.value,
                            "account_fingerprint": account_fingerprint,
                        }
                    ),
                    status,
                    error_code,
                ),
            )
