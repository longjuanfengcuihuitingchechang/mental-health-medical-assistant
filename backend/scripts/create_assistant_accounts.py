from __future__ import annotations

import argparse
import csv
import os
import secrets
import sqlite3
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.identifiers import IdentifierProtector  # noqa: E402
from app.core.passwords import PasswordHasher  # noqa: E402
from scripts.bootstrap_accounts import make_synthetic_id  # noqa: E402


DEFAULT_DATABASE_PATH = Path(r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db")
DEFAULT_PEPPER_PATH = PROJECT_ROOT / "private" / "auth_pepper.key"
DEFAULT_CREDENTIALS_PATH = PROJECT_ROOT / "private" / "assistant_accounts.csv"


def create_assistant_accounts(
    *,
    database_path: Path,
    pepper_path: Path,
    credentials_path: Path,
    password_iterations: int = 600_000,
    required_drive: str | None = "E:",
) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    if required_drive and database_path.drive.upper() != required_drive.upper():
        raise ValueError(f"正式数据库必须位于 {required_drive}：{database_path}")
    if credentials_path.exists():
        raise FileExistsError(f"凭据文件已存在，拒绝覆盖：{credentials_path}")
    pepper = pepper_path.read_bytes()
    if len(pepper) < 32:
        raise ValueError("认证 pepper 长度不能少于 32 字节")
    protector = IdentifierProtector(pepper)
    password_hasher = PasswordHasher(iterations=password_iterations)
    now = datetime.now(UTC).isoformat()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    created = []
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        version = int(connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0])
        if version < 6:
            raise RuntimeError("数据库 schema 版本低于 6，请先执行迁移")
        if connection.execute("SELECT COUNT(*) FROM users WHERE role = 'assistant'").fetchone()[0]:
            raise RuntimeError("数据库已存在助理账号，拒绝重复创建")
        next_value = int(
            connection.execute(
                "SELECT next_value FROM account_sequences WHERE prefix = 'S'"
            ).fetchone()[0]
        )
        for offset in range(2):
            sequence = next_value + offset
            account = f"S{sequence:03d}"
            password = secrets.token_urlsafe(18)
            phone = f"1889100{sequence:04d}"
            email = f"{account.lower()}@example.invalid"
            id_card = make_synthetic_id(900 + sequence, date(1985, 1, min(sequence, 28)))
            created.append(
                {
                    "id": str(uuid.uuid4()),
                    "account": account,
                    "display_name": f"演示助理{offset + 1:02d}",
                    "password": password,
                    "password_hash": password_hasher.hash_password(password),
                    "phone": phone,
                    "email": email,
                    "id_card": id_card,
                }
            )

        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path = credentials_path.with_suffix(".pending.csv")
        if pending_path.exists():
            raise FileExistsError(f"存在未完成的凭据文件：{pending_path}")
        with pending_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("role", "account", "initial_password", "display_name", "phone", "email", "must_change_password", "data_notice"),
            )
            writer.writeheader()
            for user in created:
                writer.writerow(
                    {
                        "role": "assistant",
                        "account": user["account"],
                        "initial_password": user["password"],
                        "display_name": user["display_name"],
                        "phone": user["phone"],
                        "email": user["email"],
                        "must_change_password": 1,
                        "data_notice": "synthetic_demo_data",
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(pending_path, 0o600)

        connection.execute("BEGIN IMMEDIATE")
        for user in created:
            connection.execute(
                """
                INSERT INTO users (
                    id, account, password_hash, display_name, role,
                    account_status, must_change_password, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'assistant', 'active', 1, ?, ?)
                """,
                (user["id"], user["account"], user["password_hash"], user["display_name"], now, now),
            )
            id_info = protector.parse_id_card(user["id_card"])
            phone = protector.normalize_phone(user["phone"])
            email = protector.normalize_email(user["email"])
            connection.execute(
                """
                INSERT INTO person_profiles (
                    user_id, id_card_fingerprint, id_card_masked, phone_masked,
                    email_masked, birth_date, gender, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    protector.fingerprint("id_card", user["id_card"]),
                    protector.mask("id_card", id_info.normalized),
                    protector.mask("phone", phone),
                    protector.mask("email", email),
                    id_info.birth_date.isoformat(),
                    id_info.gender,
                    now,
                    now,
                ),
            )
            for kind, raw, masked in (
                ("account", user["account"], user["account"]),
                ("phone", phone, protector.mask("phone", phone)),
                ("email", email, protector.mask("email", email)),
            ):
                connection.execute(
                    """
                    INSERT INTO user_login_identifiers (
                        id, user_id, identifier_type, identifier_fingerprint,
                        identifier_masked, verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (str(uuid.uuid4()), user["id"], kind, protector.fingerprint(kind, raw), masked, now),
                )
            connection.execute(
                """
                INSERT INTO assistant_profiles (
                    user_id, employee_no, employment_status, created_at, updated_at
                ) VALUES (?, ?, 'active', ?, ?)
                """,
                (user["id"], user["account"], now, now),
            )
        connection.execute(
            "UPDATE account_sequences SET next_value = ? WHERE prefix = 'S'",
            (next_value + 2,),
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                id, action, target_type, filters_json, result_count, status
            ) VALUES (?, 'bootstrap.create_assistants', 'users',
                      '{"assistant":2,"synthetic":true}', 2, 'success')
            """,
            (str(uuid.uuid4()),),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    pending_path.replace(credentials_path)
    os.chmod(credentials_path, 0o600)
    return {
        "database_path": str(database_path),
        "credentials_path": str(credentials_path),
        "assistant_count": 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="创建两个合成助理账号")
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--pepper-path", type=Path, default=DEFAULT_PEPPER_PATH)
    parser.add_argument("--credentials-path", type=Path, default=DEFAULT_CREDENTIALS_PATH)
    parser.add_argument("--password-iterations", type=int, default=600_000)
    args = parser.parse_args()
    result = create_assistant_accounts(
        database_path=args.database_path,
        pepper_path=args.pepper_path,
        credentials_path=args.credentials_path,
        password_iterations=args.password_iterations,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
