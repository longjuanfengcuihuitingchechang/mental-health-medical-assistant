from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


PROJECT_BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
SCHEMA_PATH = PROJECT_BACKEND / "db" / "schema.sql"


def validate_target(path: Path, required_drive: str = "E:") -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("数据库路径必须是绝对路径")
    if path.drive.upper() != required_drive.upper():
        raise ValueError(f"数据库必须创建在 {required_drive}，当前路径为 {path}")
    if not Path(f"{required_drive}\\").exists():
        raise RuntimeError(f"目标移动硬盘 {required_drive} 不可用")
    return path


def initialize_database(database_path: Path) -> dict[str, str | int]:
    target = validate_target(database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        connection.executescript(schema_sql)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        user_version = int(
            connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0]
        )
        connection.commit()
    finally:
        connection.close()

    return {
        "database_path": str(target),
        "journal_mode": journal_mode,
        "integrity_check": integrity,
        "schema_version": user_version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化心理健康助手 SQLite 数据库")
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
    )
    args = parser.parse_args()
    result = initialize_database(args.database_path)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
