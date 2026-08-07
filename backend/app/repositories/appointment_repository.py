from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.db.connection import SQLiteConnectionFactory


ACTIVE_STATUSES = (
    "queued",
    "awaiting_patient_decision",
    "awaiting_doctor_decision",
    "queued_over_capacity",
)


class AppointmentRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory):
        self.connection_factory = connection_factory

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.role, u.account_status, u.blacklisted, u.display_name,
                       d.employment_status AS doctor_employment_status,
                       a.employment_status AS assistant_employment_status
                FROM users u
                LEFT JOIN doctor_profiles d ON d.user_id = u.id
                LEFT JOIN assistant_profiles a ON a.user_id = u.id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def completed_visit_count(self, patient_user_id: str) -> int:
        with self.connection_factory.connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM clinical_visit_summaries
                    WHERE patient_user_id = ? AND status = 'completed'
                    """,
                    (patient_user_id,),
                ).fetchone()[0]
            )

    def appointment_summary(self, doctor_user_id: str, appointment_date: str) -> dict[str, Any]:
        with self.connection_factory.connect() as connection:
            doctor = connection.execute(
                """SELECT u.id,u.display_name,u.account_status,d.employment_status,
                          COALESCE(v.availability_status,'unknown') AS availability_status,
                          v.expected_available_at,c.capacity
                   FROM users u JOIN doctor_profiles d ON d.user_id=u.id
                   LEFT JOIN doctor_availability v ON v.doctor_user_id=u.id
                   LEFT JOIN doctor_daily_capacities c ON c.doctor_user_id=u.id AND c.appointment_date=?
                   WHERE u.id=? AND u.role='doctor'""",
                (appointment_date, doctor_user_id),
            ).fetchone()
            if not doctor:
                raise ValueError("医生不存在")
            result = dict(doctor)
            result["appointment_date"] = appointment_date
            result["appointment_count"] = self._active_count(connection, doctor_user_id, appointment_date)
        return result

    def get_night_shift(self, shift_date: str) -> dict[str, Any] | None:
        with self.connection_factory.connect() as connection:
            row = connection.execute(
                "SELECT n.shift_date,n.doctor_user_id,u.display_name AS doctor_display_name,n.assigned_by_user_id FROM doctor_night_shifts n JOIN users u ON u.id=n.doctor_user_id WHERE n.shift_date=?",
                (shift_date,),
            ).fetchone()
        return dict(row) if row else None

    def set_capacity(
        self,
        *,
        doctor_user_id: str,
        appointment_date: str,
        capacity: int,
        now: str,
    ) -> dict[str, int]:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO doctor_daily_capacities (
                        doctor_user_id, appointment_date, capacity, version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(doctor_user_id, appointment_date) DO UPDATE SET
                        capacity = excluded.capacity,
                        version = doctor_daily_capacities.version + 1,
                        updated_at = excluded.updated_at
                    """,
                    (doctor_user_id, appointment_date, capacity, now, now),
                )
                row = connection.execute(
                    """
                    SELECT capacity, version FROM doctor_daily_capacities
                    WHERE doctor_user_id = ? AND appointment_date = ?
                    """,
                    (doctor_user_id, appointment_date),
                ).fetchone()
                count = self._active_count(connection, doctor_user_id, appointment_date)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"capacity": int(row["capacity"]), "version": int(row["version"]), "count": count}

    def create_appointment(
        self,
        *,
        patient_user_id: str,
        doctor_user_id: str,
        appointment_date: str,
        now: str,
    ) -> dict[str, Any]:
        appointment_id = str(uuid.uuid4())
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                capacity_row = connection.execute(
                    """
                    SELECT capacity FROM doctor_daily_capacities
                    WHERE doctor_user_id = ? AND appointment_date = ?
                    """,
                    (doctor_user_id, appointment_date),
                ).fetchone()
                capacity = int(capacity_row["capacity"]) if capacity_row else None
                count = self._active_count(connection, doctor_user_id, appointment_date)
                queue_number = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(queue_number), 0) + 1
                        FROM patient_appointments
                        WHERE doctor_user_id = ? AND appointment_date = ?
                        """,
                        (doctor_user_id, appointment_date),
                    ).fetchone()[0]
                )
                status = "queued" if capacity is not None and count < capacity else "awaiting_patient_decision"
                connection.execute(
                    """
                    INSERT INTO patient_appointments (
                        id, patient_user_id, doctor_user_id, appointment_date,
                        queue_number, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (appointment_id, patient_user_id, doctor_user_id, appointment_date, queue_number, status, now, now),
                )
                connection.execute(
                    """
                    INSERT INTO appointment_events (
                        id, appointment_id, actor_user_id, event_type,
                        to_status, created_at
                    ) VALUES (?, ?, ?, 'appointment.created', ?, ?)
                    """,
                    (str(uuid.uuid4()), appointment_id, patient_user_id, status, now),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RuntimeError("患者已存在同一医生同一天的活动预约") from error
            except Exception:
                connection.rollback()
                raise
        return {
            "id": appointment_id,
            "status": status,
            "capacity": capacity,
            "appointment_count": count + 1,
            "queue_number": queue_number,
        }

    def patient_decide(
        self,
        *,
        patient_user_id: str,
        appointment_id: str,
        decision: str,
        now: str,
    ) -> str:
        target = "change_requested" if decision == "switch_doctor" else "awaiting_doctor_decision"
        return self._transition(
            appointment_id=appointment_id,
            actor_user_id=patient_user_id,
            owner_field="patient_user_id",
            expected="awaiting_patient_decision",
            target=target,
            updates={"patient_decision": decision},
            event_type="appointment.patient_decision",
            now=now,
        )

    def doctor_decide(
        self,
        *,
        doctor_user_id: str,
        appointment_id: str,
        decision: str,
        communication_mode: str | None,
        patient_message: str,
        now: str,
    ) -> str:
        target = (
            "queued_over_capacity"
            if decision == "accept"
            else f"declined_{communication_mode}"
        )
        return self._transition(
            appointment_id=appointment_id,
            actor_user_id=doctor_user_id,
            owner_field="doctor_user_id",
            expected="awaiting_doctor_decision",
            target=target,
            updates={
                "doctor_decision": decision,
                "communication_mode": communication_mode,
                "patient_message": patient_message,
            },
            event_type="appointment.doctor_decision",
            now=now,
        )

    def assign_night_shift(
        self,
        *,
        shift_date: str,
        doctor_user_id: str,
        assigned_by_user_id: str,
        now: str,
    ) -> dict[str, Any]:
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO doctor_night_shifts (
                        shift_date, doctor_user_id, assigned_by_user_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (shift_date, doctor_user_id, assigned_by_user_id, now, now),
                )
                row = connection.execute(
                    "SELECT display_name FROM users WHERE id = ?",
                    (doctor_user_id,),
                ).fetchone()
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RuntimeError("该日期已安排夜班医生") from error
            except Exception:
                connection.rollback()
                raise
        return {"display_name": row["display_name"]}

    def list_pending_decisions(
        self,
        *,
        doctor_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        condition = "AND a.doctor_user_id = ?" if doctor_user_id else ""
        params = (doctor_user_id,) if doctor_user_id else ()
        with self.connection_factory.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT a.id AS appointment_id, a.patient_user_id,
                       patient.display_name AS patient_display_name,
                       a.doctor_user_id,
                       doctor.display_name AS doctor_display_name,
                       a.appointment_date, a.queue_number AS queue_position,
                       a.status
                FROM patient_appointments a
                JOIN users patient ON patient.id = a.patient_user_id
                JOIN users doctor ON doctor.id = a.doctor_user_id
                WHERE a.status = 'awaiting_doctor_decision' {condition}
                ORDER BY a.appointment_date, a.queue_number
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def _transition(
        self,
        *,
        appointment_id: str,
        actor_user_id: str,
        owner_field: str,
        expected: str,
        target: str,
        updates: dict[str, Any],
        event_type: str,
        now: str,
    ) -> str:
        allowed_owner_fields = {"patient_user_id", "doctor_user_id"}
        if owner_field not in allowed_owner_fields:
            raise ValueError("invalid owner field")
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [target, now]
        for column, value in updates.items():
            if column not in {"patient_decision", "doctor_decision", "communication_mode", "patient_message"}:
                raise ValueError("invalid appointment update")
            assignments.append(f"{column} = ?")
            params.append(value)
        params.extend([appointment_id, actor_user_id, expected])
        with self.connection_factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    f"""
                    UPDATE patient_appointments SET {', '.join(assignments)}
                    WHERE id = ? AND {owner_field} = ? AND status = ?
                    """,
                    params,
                )
                if cursor.rowcount != 1:
                    raise PermissionError("预约不存在、无权处理或状态已变化")
                connection.execute(
                    """
                    INSERT INTO appointment_events (
                        id, appointment_id, actor_user_id, event_type,
                        from_status, to_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), appointment_id, actor_user_id, event_type, expected, target, now),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return target

    @staticmethod
    def _active_count(connection, doctor_user_id: str, appointment_date: str) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        return int(
            connection.execute(
                f"""
                SELECT COUNT(*) FROM patient_appointments
                WHERE doctor_user_id = ? AND appointment_date = ?
                  AND status IN ({placeholders})
                """,
                (doctor_user_id, appointment_date, *ACTIVE_STATUSES),
            ).fetchone()[0]
        )
