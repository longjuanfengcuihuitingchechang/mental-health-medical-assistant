from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.db.connection import SQLiteConnectionFactory


class SecurityRepository:
    def __init__(self, factory: SQLiteConnectionFactory):
        self.factory = factory

    def consume_rate_limit(
        self,
        *,
        bucket_key: str,
        limit: int,
        window_seconds: int,
        now: datetime,
    ) -> tuple[bool, int, int]:
        with self.factory.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """SELECT window_started_at,request_count,blocked_until
                       FROM api_rate_limits WHERE bucket_key=?""",
                    (bucket_key,),
                ).fetchone()
                window_start = now
                count = 0
                if row:
                    existing_start = datetime.fromisoformat(row["window_started_at"])
                    if existing_start.tzinfo is None:
                        existing_start = existing_start.replace(tzinfo=UTC)
                    blocked_until = (
                        datetime.fromisoformat(row["blocked_until"])
                        if row["blocked_until"]
                        else None
                    )
                    if blocked_until and blocked_until.tzinfo is None:
                        blocked_until = blocked_until.replace(tzinfo=UTC)
                    if blocked_until and blocked_until > now:
                        retry = max(1, int((blocked_until - now).total_seconds() + 0.999))
                        connection.commit()
                        return False, retry, int(row["request_count"])
                    if now - existing_start < timedelta(seconds=window_seconds):
                        window_start = existing_start
                        count = int(row["request_count"])
                count += 1
                window_end = window_start + timedelta(seconds=window_seconds)
                allowed = count <= limit
                blocked_until_value = window_end.isoformat() if not allowed else None
                connection.execute(
                    """INSERT INTO api_rate_limits (
                           bucket_key,window_started_at,request_count,blocked_until,updated_at
                       ) VALUES (?,?,?,?,?)
                       ON CONFLICT(bucket_key) DO UPDATE SET
                           window_started_at=excluded.window_started_at,
                           request_count=excluded.request_count,
                           blocked_until=excluded.blocked_until,
                           updated_at=excluded.updated_at""",
                    (
                        bucket_key,
                        window_start.isoformat(),
                        count,
                        blocked_until_value,
                        now.isoformat(),
                    ),
                )
                connection.commit()
                retry = max(1, int((window_end - now).total_seconds() + 0.999))
                return allowed, retry if not allowed else 0, count
            except Exception:
                connection.rollback()
                raise

    def append_audit(
        self,
        *,
        actor_user_id: str | None,
        action: str,
        target_type: str,
        status: str,
        error_code: str | None,
        request_id: str | None,
        ip_fingerprint: str | None,
        resource_fingerprint: str | None,
        metadata: dict,
    ) -> None:
        with self.factory.connect() as connection:
            connection.execute(
                """INSERT INTO audit_events (
                       id,actor_user_id,action,target_type,filters_json,result_count,
                       status,error_code,request_id,ip_fingerprint,
                       resource_fingerprint,metadata_json
                   ) VALUES (?,?,?,?,?,0,?,?,?,?,?,?)""",
                (
                    f"audit_{uuid.uuid4().hex}",
                    actor_user_id,
                    action,
                    target_type,
                    "{}",
                    status,
                    error_code,
                    request_id,
                    ip_fingerprint,
                    resource_fingerprint,
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                ),
            )
