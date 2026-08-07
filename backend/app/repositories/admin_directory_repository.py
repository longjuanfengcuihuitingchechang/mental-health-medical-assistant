from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from typing import Any

from app.db.connection import SQLiteConnectionFactory
from app.schemas.admin_directory import (
    AdminDirectoryRequest,
    DirectoryTarget,
    UserRole,
)


class AdminDirectoryRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory):
        self.connection_factory = connection_factory

    def get_requester(self, requester_user_id: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                """
                SELECT id, role, account_status
                FROM users
                WHERE id = ?
                """,
                (requester_user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_directory(
        self,
        request: AdminDirectoryRequest,
    ) -> tuple[list[dict[str, Any]], int]:
        select_sql, from_sql, role_condition = self._query_parts(request.target_role)
        conditions = [role_condition]
        params: list[Any] = []

        if request.keyword:
            keyword_fields = ["u.account", "u.display_name"]
            if request.target_role is DirectoryTarget.PATIENT:
                keyword_fields.append("p.medical_record_no")
            elif request.target_role is DirectoryTarget.DOCTOR:
                keyword_fields.append("d.employee_no")
            elif request.target_role is DirectoryTarget.ASSISTANT:
                keyword_fields.append("s.employee_no")
            else:
                keyword_fields.append("a.employee_no")
            conditions.append(
                "(" + " OR ".join(f"{field} LIKE ?" for field in keyword_fields) + ")"
            )
            params.extend([f"%{request.keyword}%"] * len(keyword_fields))

        if request.account_status:
            conditions.append("u.account_status = ?")
            params.append(request.account_status.value)
        if request.blacklisted is not None:
            conditions.append("u.blacklisted = ?")
            params.append(int(request.blacklisted))
        if request.employment_status:
            profile_alias = "d" if request.target_role is DirectoryTarget.DOCTOR else "s"
            conditions.append(f"{profile_alias}.employment_status = ?")
            params.append(request.employment_status.value)

        where_sql = " AND ".join(conditions)
        count_sql = f"SELECT COUNT(*) {from_sql} WHERE {where_sql}"
        data_sql = (
            f"{select_sql} {from_sql} WHERE {where_sql} "
            "ORDER BY u.display_name COLLATE NOCASE, u.account COLLATE NOCASE "
            "LIMIT ? OFFSET ?"
        )

        with self.connection_factory.connect() as connection:
            total = int(connection.execute(count_sql, params).fetchone()[0])
            rows = connection.execute(
                data_sql,
                [*params, request.limit, request.offset],
            ).fetchall()
        return [dict(row) for row in rows], total

    def write_audit(
        self,
        *,
        requester_user_id: str | None,
        request: AdminDirectoryRequest,
        status: str,
        result_count: int,
        error_code: str | None = None,
    ) -> None:
        safe_filters = asdict(request)
        safe_filters["keyword"] = bool(request.keyword)
        safe_filters["target_role"] = request.target_role.value
        if request.account_status:
            safe_filters["account_status"] = request.account_status.value
        if request.employment_status:
            safe_filters["employment_status"] = request.employment_status.value

        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        id, actor_user_id, action, target_type,
                        filters_json, result_count, status, error_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        requester_user_id,
                        "directory.list",
                        request.target_role.value,
                        json.dumps(safe_filters, ensure_ascii=False),
                        result_count,
                        status,
                        error_code,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _query_parts(target_role: DirectoryTarget) -> tuple[str, str, str]:
        common = """
            u.id AS user_id,
            u.account,
            u.display_name,
            u.account_status,
            u.blacklisted,
            u.created_at,
            u.updated_at
        """
        if target_role is DirectoryTarget.PATIENT:
            return (
                f"SELECT {common}, p.medical_record_no, p.assigned_doctor_user_id",
                "FROM users u JOIN patient_profiles p ON p.user_id = u.id",
                "u.role = 'patient'",
            )
        if target_role is DirectoryTarget.DOCTOR:
            return (
                f"""SELECT {common}, d.employee_no, d.department,
                    d.professional_title, d.employment_status""",
                "FROM users u JOIN doctor_profiles d ON d.user_id = u.id",
                "u.role = 'doctor'",
            )
        if target_role is DirectoryTarget.ASSISTANT:
            return (
                f"""SELECT {common}, s.employee_no, s.employment_status""",
                "FROM users u JOIN assistant_profiles s ON s.user_id = u.id",
                "u.role = 'assistant'",
            )
        return (
            f"SELECT {common}, u.role, a.employee_no, a.department",
            "FROM users u JOIN admin_profiles a ON a.user_id = u.id",
            "u.role IN ('admin', 'super_admin')",
        )
