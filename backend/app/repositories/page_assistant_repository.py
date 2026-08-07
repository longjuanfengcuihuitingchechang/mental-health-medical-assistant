from __future__ import annotations

import uuid
from typing import Any

from app.db.connection import SQLiteConnectionFactory


class PageAssistantRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory):
        self.connection_factory = connection_factory

    def get_patient(self, patient_user_id: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.display_name, u.role, u.account_status,
                       u.blacklisted, pp.birth_date,
                       COALESCE(mgc.consent_status, 'pending') AS guardian_consent_status
                FROM users u
                LEFT JOIN person_profiles pp ON pp.user_id = u.id
                LEFT JOIN minor_guardian_consents mgc ON mgc.patient_user_id = u.id
                WHERE u.id = ?
                """,
                (patient_user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_doctor_options(self, patient_user_id: str) -> list[dict[str, Any]]:
        with self.connection_factory.connect() as connection:
            rows = connection.execute(
                """
                WITH previous_doctors AS (
                    SELECT doctor_user_id, MAX(visited_at) AS last_visit_at
                    FROM clinical_visit_summaries
                    WHERE patient_user_id = ? AND status = 'completed'
                    GROUP BY doctor_user_id
                ), active_queue AS (
                    SELECT doctor_user_id, COUNT(*) AS queue_length
                    FROM consultation_queue
                    WHERE status IN ('waiting', 'called')
                    GROUP BY doctor_user_id
                ), patient_queue AS (
                    SELECT q.doctor_user_id,
                           1 + (
                               SELECT COUNT(*) FROM consultation_queue earlier
                               WHERE earlier.doctor_user_id = q.doctor_user_id
                                 AND earlier.status IN ('waiting', 'called')
                                 AND earlier.joined_at < q.joined_at
                           ) AS queue_position
                    FROM consultation_queue q
                    WHERE q.patient_user_id = ?
                      AND q.status IN ('waiting', 'called')
                )
                SELECT u.id AS doctor_user_id, u.display_name,
                       d.department, d.professional_title,
                       COALESCE(a.availability_status, 'unknown') AS availability_status,
                       a.expected_available_at,
                       COALESCE(q.queue_length, 0) AS queue_length,
                       pq.queue_position,
                       p.last_visit_at
                FROM users u
                JOIN doctor_profiles d ON d.user_id = u.id
                LEFT JOIN doctor_availability a ON a.doctor_user_id = u.id
                LEFT JOIN active_queue q ON q.doctor_user_id = u.id
                LEFT JOIN patient_queue pq ON pq.doctor_user_id = u.id
                LEFT JOIN previous_doctors p ON p.doctor_user_id = u.id
                WHERE u.role = 'doctor'
                  AND u.account_status = 'active'
                  AND u.blacklisted = 0
                  AND d.employment_status IN ('active', 'leave')
                ORDER BY (p.last_visit_at IS NULL), p.last_visit_at DESC,
                         CASE COALESCE(a.availability_status, 'unknown')
                             WHEN 'working' THEN 0 WHEN 'on_leave' THEN 1
                             WHEN 'off_duty' THEN 2 ELSE 3 END,
                         q.queue_length, u.display_name
                """,
                (patient_user_id, patient_user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_session(
        self,
        *,
        patient_user_id: str,
        session_id: str | None,
        page: str,
        now: str,
    ) -> str:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if session_id:
                    row = connection.execute(
                        """
                        SELECT id FROM assistant_sessions
                        WHERE id = ? AND patient_user_id = ? AND status = 'active'
                        """,
                        (session_id, patient_user_id),
                    ).fetchone()
                    if not row:
                        raise PermissionError("助手会话不存在或不属于当前患者")
                else:
                    session_id = str(uuid.uuid4())
                    connection.execute(
                        """
                        INSERT INTO assistant_sessions (
                            id, patient_user_id, last_page, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (session_id, patient_user_id, page, now, now),
                    )
                connection.execute(
                    """
                    UPDATE assistant_sessions
                    SET last_page = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (page, now, session_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return session_id

    def record_usage_event(
        self,
        *,
        patient_user_id: str,
        session_id: str,
        page: str,
        feature_key: str,
        event_type: str,
        now: str,
        introduction_limit: int = 8,
    ) -> tuple[int, bool]:
        is_open = event_type in ("page_open", "feature_open")
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT usage_count, introduction_count
                    FROM patient_feature_usage
                    WHERE patient_user_id = ? AND page = ? AND feature_key = ?
                    """,
                    (patient_user_id, page, feature_key),
                ).fetchone()
                old_usage = int(row["usage_count"]) if row else 0
                old_introductions = int(row["introduction_count"]) if row else 0
                usage_count = old_usage + int(is_open)
                introduction_shown = is_open and old_introductions < introduction_limit
                introduction_count = old_introductions + int(introduction_shown)
                connection.execute(
                    """
                    INSERT INTO patient_feature_usage (
                        patient_user_id, page, feature_key, usage_count,
                        introduction_count, first_used_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(patient_user_id, page, feature_key) DO UPDATE SET
                        usage_count = excluded.usage_count,
                        introduction_count = excluded.introduction_count,
                        last_used_at = excluded.last_used_at
                    """,
                    (
                        patient_user_id,
                        page,
                        feature_key,
                        usage_count,
                        introduction_count,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO patient_feature_usage_logs (
                        id, patient_user_id, session_id, page, feature_key,
                        event_type, usage_count, introduction_shown, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        patient_user_id,
                        session_id,
                        page,
                        feature_key,
                        event_type,
                        usage_count,
                        int(introduction_shown),
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return usage_count, introduction_shown

    def list_recent_messages(
        self,
        *,
        patient_user_id: str,
        session_id: str,
        limit: int = 12,
    ) -> list[dict[str, str]]:
        with self.connection_factory.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.role, m.content
                FROM assistant_messages m
                JOIN assistant_sessions s ON s.id = m.session_id
                WHERE m.session_id = ? AND s.patient_user_id = ?
                ORDER BY m.created_at DESC, m.rowid DESC
                LIMIT ?
                """,
                (session_id, patient_user_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def session_belongs_to_patient(
        self,
        *,
        patient_user_id: str,
        session_id: str,
    ) -> bool:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM assistant_sessions
                WHERE id = ? AND patient_user_id = ? AND status = 'active'
                """,
                (session_id, patient_user_id),
            ).fetchone()
        return row is not None

    def append_message_pair(
        self,
        *,
        session_id: str,
        page: str,
        feature_key: str,
        user_content: str,
        assistant_content: str,
        now: str,
    ) -> None:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany(
                    """
                    INSERT INTO assistant_messages (
                        id, session_id, role, page, feature_key, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (str(uuid.uuid4()), session_id, "user", page, feature_key, user_content, now),
                        (str(uuid.uuid4()), session_id, "assistant", page, feature_key, assistant_content, now),
                    ],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
