from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.db.connection import SQLiteConnectionFactory
from app.schemas.async_tasks import (
    TaskEvent,
    TaskEventType,
    TaskNotFoundError,
    TaskSnapshot,
    TaskStatus,
    TaskType,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AsyncTaskRepository:
    def __init__(self, factory: SQLiteConnectionFactory):
        self.factory = factory

    def create(
        self,
        *,
        owner_user_id: str,
        role: str,
        task_type: TaskType,
        payload: dict,
        timeout_seconds: float,
    ) -> TaskSnapshot:
        task_id = f"task_{uuid.uuid4().hex}"
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO async_tasks (
                           id,owner_user_id,task_type,role,status,input_json,
                           timeout_seconds,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        task_id,
                        owner_user_id,
                        task_type.value,
                        role,
                        TaskStatus.QUEUED.value,
                        json.dumps(payload, ensure_ascii=False),
                        timeout_seconds,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    task_id,
                    TaskEventType.CREATED,
                    {"status": TaskStatus.QUEUED.value},
                    now,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get(owner_user_id, task_id)

    def get(self, owner_user_id: str, task_id: str) -> TaskSnapshot:
        with self.factory.connect() as connection:
            row = connection.execute(
                """SELECT id,task_type,status,role,output_json,error_code,
                          cancel_requested,created_at,started_at,finished_at
                   FROM async_tasks WHERE id=? AND owner_user_id=?""",
                (task_id, owner_user_id),
            ).fetchone()
        if not row:
            raise TaskNotFoundError("任务不存在或不属于当前用户")
        return self._snapshot(row)

    def get_for_worker(self, task_id: str) -> dict | None:
        with self.factory.connect() as connection:
            row = connection.execute(
                "SELECT * FROM async_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["input"] = json.loads(data.pop("input_json"))
        return data

    def start(self, task_id: str) -> bool:
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """UPDATE async_tasks
                       SET status=?,started_at=?,updated_at=?
                       WHERE id=? AND status=? AND cancel_requested=0""",
                    (
                        TaskStatus.RUNNING.value,
                        now,
                        now,
                        task_id,
                        TaskStatus.QUEUED.value,
                    ),
                ).rowcount
                if changed:
                    self._append_event(
                        connection,
                        task_id,
                        TaskEventType.STARTED,
                        {"status": TaskStatus.RUNNING.value},
                        now,
                    )
                connection.commit()
                return bool(changed)
            except Exception:
                connection.rollback()
                raise

    def append_delta(self, task_id: str, text: str) -> TaskEvent:
        if not text:
            raise ValueError("增量内容不能为空")
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status,cancel_requested FROM async_tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
                if not row or row["status"] != TaskStatus.RUNNING.value or row["cancel_requested"]:
                    raise RuntimeError("任务已停止，不能继续写入内容")
                event = self._append_event(
                    connection,
                    task_id,
                    TaskEventType.DELTA,
                    {"text": text},
                    now,
                )
                connection.commit()
                return event
            except Exception:
                connection.rollback()
                raise

    def complete(self, task_id: str, output: dict) -> bool:
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """UPDATE async_tasks
                       SET status=?,output_json=?,finished_at=?,updated_at=?
                       WHERE id=? AND status=? AND cancel_requested=0""",
                    (
                        TaskStatus.SUCCEEDED.value,
                        json.dumps(output, ensure_ascii=False, default=str),
                        now,
                        now,
                        task_id,
                        TaskStatus.RUNNING.value,
                    ),
                ).rowcount
                if changed:
                    self._append_event(
                        connection,
                        task_id,
                        TaskEventType.COMPLETED,
                        {"status": TaskStatus.SUCCEEDED.value, "response": output},
                        now,
                    )
                connection.commit()
                return bool(changed)
            except Exception:
                connection.rollback()
                raise

    def fail(self, task_id: str, error_code: str, message: str) -> bool:
        return self._finish(
            task_id,
            TaskStatus.FAILED,
            TaskEventType.FAILED,
            error_code,
            {"status": TaskStatus.FAILED.value, "error_code": error_code, "message": message},
        )

    def cancel(self, task_id: str) -> bool:
        return self._finish(
            task_id,
            TaskStatus.CANCELLED,
            TaskEventType.CANCELLED,
            "TASK_CANCELLED",
            {"status": TaskStatus.CANCELLED.value},
        )

    def request_cancel(self, owner_user_id: str, task_id: str) -> TaskSnapshot:
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status FROM async_tasks WHERE id=? AND owner_user_id=?",
                    (task_id, owner_user_id),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("任务不存在或不属于当前用户")
                status = TaskStatus(row["status"])
                if not status.terminal:
                    connection.execute(
                        "UPDATE async_tasks SET cancel_requested=1,updated_at=? WHERE id=?",
                        (now, task_id),
                    )
                    if status in {TaskStatus.PENDING, TaskStatus.QUEUED}:
                        connection.execute(
                            """UPDATE async_tasks SET status=?,error_code=?,finished_at=?,updated_at=?
                               WHERE id=?""",
                            (TaskStatus.CANCELLED.value, "TASK_CANCELLED", now, now, task_id),
                        )
                        self._append_event(
                            connection,
                            task_id,
                            TaskEventType.CANCELLED,
                            {"status": TaskStatus.CANCELLED.value},
                            now,
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get(owner_user_id, task_id)

    def should_cancel(self, task_id: str) -> bool:
        with self.factory.connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested,status FROM async_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
        return not row or bool(row["cancel_requested"]) or TaskStatus(row["status"]).terminal

    def fail_incomplete(self, error_code: str, message: str) -> int:
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """SELECT id FROM async_tasks
                       WHERE status IN (?,?,?)""",
                    (
                        TaskStatus.PENDING.value,
                        TaskStatus.QUEUED.value,
                        TaskStatus.RUNNING.value,
                    ),
                ).fetchall()
                for row in rows:
                    connection.execute(
                        """UPDATE async_tasks
                           SET status=?,error_code=?,finished_at=?,updated_at=?
                           WHERE id=?""",
                        (TaskStatus.FAILED.value, error_code, now, now, row["id"]),
                    )
                    self._append_event(
                        connection,
                        row["id"],
                        TaskEventType.FAILED,
                        {
                            "status": TaskStatus.FAILED.value,
                            "error_code": error_code,
                            "message": message,
                        },
                        now,
                    )
                connection.commit()
                return len(rows)
            except Exception:
                connection.rollback()
                raise

    def list_events(
        self,
        owner_user_id: str,
        task_id: str,
        *,
        after: int = 0,
        limit: int = 100,
    ) -> list[TaskEvent]:
        self.get(owner_user_id, task_id)
        with self.factory.connect() as connection:
            rows = connection.execute(
                """SELECT sequence,event_type,data_json,created_at
                   FROM async_task_events
                   WHERE task_id=? AND sequence>?
                   ORDER BY sequence ASC LIMIT ?""",
                (task_id, after, limit),
            ).fetchall()
        return [
            TaskEvent(
                event_id=int(row["sequence"]),
                task_id=task_id,
                event_type=TaskEventType(row["event_type"]),
                data=json.loads(row["data_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _finish(
        self,
        task_id: str,
        status: TaskStatus,
        event_type: TaskEventType,
        error_code: str,
        event_data: dict,
    ) -> bool:
        now = _now()
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """UPDATE async_tasks
                       SET status=?,error_code=?,finished_at=?,updated_at=?
                       WHERE id=? AND status IN (?,?)""",
                    (
                        status.value,
                        error_code,
                        now,
                        now,
                        task_id,
                        TaskStatus.QUEUED.value,
                        TaskStatus.RUNNING.value,
                    ),
                ).rowcount
                if changed:
                    self._append_event(connection, task_id, event_type, event_data, now)
                connection.commit()
                return bool(changed)
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _snapshot(row) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=row["id"],
            task_type=TaskType(row["task_type"]),
            status=TaskStatus(row["status"]),
            role=row["role"],
            output=json.loads(row["output_json"]) if row["output_json"] else None,
            error_code=row["error_code"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _append_event(connection, task_id: str, event_type: TaskEventType, data: dict, now: str) -> TaskEvent:
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM async_task_events WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        )
        connection.execute(
            """INSERT INTO async_task_events (id,task_id,sequence,event_type,data_json,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                f"tevt_{uuid.uuid4().hex}",
                task_id,
                sequence,
                event_type.value,
                json.dumps(data, ensure_ascii=False, default=str),
                now,
            ),
        )
        return TaskEvent(sequence, task_id, event_type, data, now)
