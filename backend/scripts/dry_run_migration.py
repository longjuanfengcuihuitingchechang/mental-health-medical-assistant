from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = Path(r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db")


def dry_run(database_path: Path, migration_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    if not migration_path.is_file():
        raise FileNotFoundError(f"迁移文件不存在：{migration_path}")
    source = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(":memory:")
    try:
        source.backup(target)
        before_users = int(target.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        target.executescript(migration_path.read_text(encoding="utf-8"))
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        after_users = int(target.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        version = int(target.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0])
    finally:
        source.close()
        target.close()
    if integrity != "ok" or foreign_key_errors or before_users != after_users:
        raise RuntimeError("迁移演练完整性检查失败")
    return {
        "schema_version": version,
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_key_errors),
        "users_before": before_users,
        "users_after": after_users,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="在内存副本中演练单个 SQLite migration")
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--migration-path", type=Path, required=True)
    args = parser.parse_args()
    for key, value in dry_run(args.database_path, args.migration_path).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
