from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
MIGRATIONS_DIR = BACKEND_ROOT / "db" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_.*\.sql$")


def validate_target(path: Path, required_drive: str = "E:") -> Path:
    if not path.is_absolute() or path.drive.upper() != required_drive.upper():
        raise ValueError(f"数据库必须位于 {required_drive}：{path}")
    if not path.is_file():
        raise FileNotFoundError(f"数据库不存在：{path}")
    return path


def migrate_database(database_path: Path) -> list[int]:
    target = validate_target(database_path)
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if match:
            migrations.append((int(match.group(1)), path))

    connection = sqlite3.connect(target)
    applied: list[int] = []
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        current = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_metadata"
            ).fetchone()[0]
        )
        for version, path in migrations:
            if version <= current:
                continue
            connection.executescript(path.read_text(encoding="utf-8"))
            connection.commit()
            applied.append(version)
            current = version
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"迁移后完整性检查失败：{integrity}")
    finally:
        connection.close()
    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移心理健康助手数据库")
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
    )
    args = parser.parse_args()
    applied = migrate_database(args.database_path)
    print(f"applied_versions: {applied}")


if __name__ == "__main__":
    main()
