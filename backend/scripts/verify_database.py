from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
EXPECTED_TABLES = {
    "schema_metadata",
    "users",
    "patient_profiles",
    "doctor_profiles",
    "admin_profiles",
    "audit_events",
    "login_security_states",
    "user_sessions",
    "person_profiles",
    "user_login_identifiers",
    "registration_requests",
    "account_sequences",
    "doctor_availability",
    "clinical_visit_summaries",
    "consultation_queue",
    "minor_guardian_consents",
    "assistant_sessions",
    "assistant_messages",
    "patient_feature_usage",
    "patient_feature_usage_logs",
    "assistant_profiles",
    "doctor_daily_capacities",
    "patient_appointments",
    "appointment_events",
    "doctor_night_shifts",
    "idempotency_records",
    "api_rate_limits",
    "agent_runs",
    "agent_run_events",
    "tool_calls",
    "work_assistant_sessions",
    "work_assistant_messages",
    "medicine_inventory",
    "async_tasks",
    "async_task_events",
}


def verify_database(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    uri = f"file:{database_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing_tables = sorted(EXPECTED_TABLES - tables)
        schema_version = connection.execute(
            "SELECT MAX(version) FROM schema_metadata"
        ).fetchone()[0]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in sorted(EXPECTED_TABLES - {"schema_metadata"})
        }
    finally:
        connection.close()

    if integrity != "ok":
        raise RuntimeError(f"数据库完整性检查失败：{integrity}")
    if missing_tables:
        raise RuntimeError(f"数据库缺少表：{', '.join(missing_tables)}")
    if int(schema_version) < 9:
        raise RuntimeError(f"数据库 schema 版本过低：{schema_version}")

    return {
        "database_path": str(database_path),
        "integrity_check": integrity,
        "schema_version": schema_version,
        "tables": sorted(EXPECTED_TABLES),
        "row_counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只读验证心理健康助手数据库")
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
    )
    args = parser.parse_args()
    result = verify_database(args.database_path)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
