from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from app.core.identifiers import IdentifierProtector
from app.db.connection import SQLiteConnectionFactory
from app.schemas.registration import (
    ApprovalAction,
    RegistrationConflictError,
    RegistrationRequest,
    RegistrationRole,
    RegistrationStateError,
)


class RegistrationRepository:
    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
        identifier_protector: IdentifierProtector,
    ):
        self.connection_factory = connection_factory
        self.identifier_protector = identifier_protector

    def create_registration(
        self,
        *,
        request: RegistrationRequest,
        password_hash: str,
        id_card_fingerprint: str,
        id_card_masked: str,
        phone_fingerprint: str,
        phone_masked: str,
        email_fingerprint: str,
        email_masked: str,
        birth_date: str,
        gender: str,
        created_at: datetime,
    ) -> dict[str, str | None]:
        prefix = "P" if request.role is RegistrationRole.PATIENT else "D"
        user_id = str(uuid.uuid4())
        registration_request_id = (
            str(uuid.uuid4()) if request.role is RegistrationRole.DOCTOR else None
        )
        now = created_at.isoformat()

        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                account = self._allocate_account(connection, prefix)
                account_status = (
                    "active"
                    if request.role is RegistrationRole.PATIENT
                    else "pending"
                )
                connection.execute(
                    """
                    INSERT INTO users (
                        id, account, password_hash, display_name, role,
                        account_status, must_change_password,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        user_id,
                        account,
                        password_hash,
                        request.display_name,
                        request.role.value,
                        account_status,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO person_profiles (
                        user_id, id_card_fingerprint, id_card_masked,
                        phone_masked, email_masked, birth_date, gender,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        id_card_fingerprint,
                        id_card_masked,
                        phone_masked,
                        email_masked,
                        birth_date,
                        gender,
                        now,
                        now,
                    ),
                )
                self._insert_identifier(
                    connection,
                    user_id,
                    "account",
                    self.identifier_protector.fingerprint("account", account),
                    account,
                    now,
                )
                self._insert_identifier(
                    connection, user_id, "phone", phone_fingerprint, phone_masked, now
                )
                self._insert_identifier(
                    connection, user_id, "email", email_fingerprint, email_masked, now
                )

                if request.role is RegistrationRole.PATIENT:
                    connection.execute(
                        """
                        INSERT INTO patient_profiles (
                            user_id, medical_record_no, created_at, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (user_id, account, now, now),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO registration_requests (
                            id, user_id, requested_role, status, department,
                            professional_title, submitted_at
                        ) VALUES (?, ?, 'doctor', 'pending', ?, ?, ?)
                        """,
                        (
                            registration_request_id,
                            user_id,
                            request.department,
                            request.professional_title,
                            now,
                        ),
                    )

                connection.execute(
                    """
                    INSERT INTO audit_events (
                        id, actor_user_id, action, target_type,
                        filters_json, result_count, status
                    ) VALUES (?, ?, 'registration.submit', ?, ?, 1, 'success')
                    """,
                    (
                        str(uuid.uuid4()),
                        user_id,
                        request.role.value,
                        json.dumps({"role": request.role.value}),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise RegistrationConflictError(
                    "身份证、手机号或邮箱已被注册"
                ) from exc
            except Exception:
                connection.rollback()
                raise

        return {
            "user_id": user_id,
            "account": account,
            "registration_request_id": registration_request_id,
        }

    def get_requester(self, requester_user_id: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                "SELECT id, role, account_status FROM users WHERE id = ?",
                (requester_user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_doctor_registrations(self, status: str, limit: int, offset: int) -> tuple[list[dict], int]:
        with self.connection_factory.connect() as connection:
            rows = connection.execute(
                """SELECT rr.id AS registration_request_id,u.account,u.display_name,
                          rr.status,rr.department,rr.professional_title,rr.submitted_at,
                          rr.reviewed_at,rr.review_note,p.phone_masked,p.email_masked
                   FROM registration_requests rr JOIN users u ON u.id=rr.user_id
                   JOIN person_profiles p ON p.user_id=u.id
                   WHERE rr.status=? ORDER BY rr.submitted_at DESC LIMIT ? OFFSET ?""",
                (status, limit, offset),
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM registration_requests WHERE status=?", (status,)).fetchone()[0]
        return [dict(row) for row in rows], int(total)

    def review_doctor_registration(
        self,
        *,
        requester_user_id: str,
        registration_request_id: str,
        action: ApprovalAction,
        review_note: str | None,
        reviewed_at: datetime,
    ) -> dict[str, str]:
        now = reviewed_at.isoformat()
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT rr.user_id, rr.department, rr.professional_title,
                           rr.status, u.account
                    FROM registration_requests rr
                    JOIN users u ON u.id = rr.user_id
                    WHERE rr.id = ?
                    """,
                    (registration_request_id,),
                ).fetchone()
                if not row or row["status"] != "pending":
                    raise RegistrationStateError("注册申请不存在或已处理")

                final_status = (
                    "approved" if action is ApprovalAction.APPROVE else "rejected"
                )
                account_status = (
                    "active" if action is ApprovalAction.APPROVE else "disabled"
                )
                connection.execute(
                    """
                    UPDATE registration_requests
                    SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (
                        final_status,
                        requester_user_id,
                        now,
                        review_note,
                        registration_request_id,
                    ),
                )
                connection.execute(
                    "UPDATE users SET account_status = ?, updated_at = ? WHERE id = ?",
                    (account_status, now, row["user_id"]),
                )
                if action is ApprovalAction.APPROVE:
                    connection.execute(
                        """
                        INSERT INTO doctor_profiles (
                            user_id, employee_no, department, professional_title,
                            employment_status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (
                            row["user_id"],
                            row["account"],
                            row["department"],
                            row["professional_title"],
                            now,
                            now,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        id, actor_user_id, action, target_type,
                        filters_json, result_count, status
                    ) VALUES (?, ?, ?, 'doctor_registration', ?, 1, 'success')
                    """,
                    (
                        str(uuid.uuid4()),
                        requester_user_id,
                        f"registration.{action.value}",
                        json.dumps(
                            {
                                "decision": action.value,
                            }
                        ),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"account": row["account"], "status": final_status}

    @staticmethod
    def _allocate_account(connection: sqlite3.Connection, prefix: str) -> str:
        row = connection.execute(
            "SELECT next_value FROM account_sequences WHERE prefix = ?",
            (prefix,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"账号序列不存在：{prefix}")
        value = int(row[0])
        connection.execute(
            "UPDATE account_sequences SET next_value = ? WHERE prefix = ?",
            (value + 1, prefix),
        )
        return f"{prefix}{value:03d}"

    @staticmethod
    def _insert_identifier(
        connection: sqlite3.Connection,
        user_id: str,
        identifier_type: str,
        identifier_fingerprint: str,
        identifier_masked: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO user_login_identifiers (
                id, user_id, identifier_type, identifier_fingerprint,
                identifier_masked, verified, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                identifier_type,
                identifier_fingerprint,
                identifier_masked,
                created_at,
            ),
        )
