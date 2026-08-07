from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.connection import SQLiteConnectionFactory


class WorkAssistantRepository:
    def __init__(self, factory: SQLiteConnectionFactory):
        self.factory = factory

    def get_user(self, user_id: str) -> dict | None:
        with self.factory.connect() as connection:
            row = connection.execute(
                "SELECT id, role, account_status, blacklisted FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def ensure_session(self, owner: str, role: str, session_id: str | None, page: str) -> str:
        now = datetime.now(UTC).isoformat()
        with self.factory.connect() as connection:
            if session_id:
                row = connection.execute(
                    "SELECT owner_user_id, role FROM work_assistant_sessions WHERE id = ? AND status = 'active'",
                    (session_id,),
                ).fetchone()
                if not row or row[0] != owner or row[1] != role:
                    raise PermissionError("工作助手会话不存在或不属于当前用户")
                connection.execute(
                    "UPDATE work_assistant_sessions SET last_page = ?, updated_at = ? WHERE id = ?",
                    (page, now, session_id),
                )
                return session_id
            new_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO work_assistant_sessions (id, owner_user_id, role, last_page, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (new_id, owner, role, page, now, now),
            )
            return new_id

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("工作助手 Repository 仅允许固定只读查询")
        with self.factory.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def create_run(self, user_id: str, agent_type: str, session_id: str, input_data: dict) -> str:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self.factory.connect() as connection:
            connection.execute(
                "INSERT INTO agent_runs (id,user_id,agent_type,assistant_session_id,status,current_node,input_json,created_at,updated_at,started_at) VALUES (?, ?, ?, ?, 'RUNNING', 'tool_selection', ?, ?, ?, ?)",
                (run_id, user_id, agent_type, session_id, json.dumps(input_data, ensure_ascii=False), now, now, now),
            )
        return run_id

    def save_tool_call(self, run_id: str, name: str, status: str, latency_ms: int, summary: dict, error_code: str | None = None) -> str:
        call_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self.factory.connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls (id,agent_run_id,tool_name,arguments_json,result_summary_json,status,latency_ms,error_code,created_at,finished_at) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)",
                (call_id, run_id, name, json.dumps(summary, ensure_ascii=False), status, latency_ms, error_code, now, now),
            )
        return call_id

    def finish_run(self, run_id: str, status: str, output: dict | None, error_code: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with self.factory.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status=?, current_node=?, output_json=?, error_code=?, finished_at=?, updated_at=? WHERE id=?",
                (status, "completed" if status == "SUCCEEDED" else "failed", json.dumps(output, ensure_ascii=False) if output else None, error_code, now, now, run_id),
            )

    def append_pair(self, session_id: str, page: str, feature: str, user_text: str, answer: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.factory.connect() as connection:
            for role, content in (("user", user_text), ("assistant", answer)):
                connection.execute(
                    "INSERT INTO work_assistant_messages (id,session_id,role,page,feature_key,content,created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), session_id, role, page, feature, content[:4000], now),
                )
