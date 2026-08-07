from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.identifiers import (  # noqa: E402
    ID_CARD_CHECK_CODES,
    ID_CARD_WEIGHTS,
    IdentifierProtector,
)
from app.core.passwords import PasswordHasher  # noqa: E402


DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
DEFAULT_PRIVATE_DIR = PROJECT_ROOT / "private"
DEFAULT_PEPPER_PATH = DEFAULT_PRIVATE_DIR / "auth_pepper.key"
DEFAULT_CREDENTIALS_PATH = DEFAULT_PRIVATE_DIR / "initial_accounts.csv"


@dataclass(slots=True)
class BootstrapUser:
    user_id: str
    role: str
    account: str
    display_name: str
    password: str
    password_hash: str
    phone: str
    email: str
    id_card: str
    department: str | None = None
    professional_title: str | None = None


def ensure_pepper(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        secret = path.read_bytes()
        if len(secret) < 32:
            raise ValueError(f"已有 pepper 文件长度不足：{path}")
        return secret
    secret = secrets.token_bytes(32)
    with path.open("xb") as handle:
        handle.write(secret)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    return secret


def make_synthetic_id(sequence: int, birth_date: date) -> str:
    base = f"999999{birth_date:%Y%m%d}{sequence:03d}"
    total = sum(int(number) * weight for number, weight in zip(base, ID_CARD_WEIGHTS))
    return base + ID_CARD_CHECK_CODES[total % 11]


def build_users(
    sequence_starts: dict[str, int],
    password_hasher: PasswordHasher,
) -> list[BootstrapUser]:
    specs: list[tuple[str, str, str | None, str | None]] = [
        ("super_admin", "最高管理员", "系统管理", None),
        ("admin", "普通管理员01", "运营管理", None),
        ("admin", "普通管理员02", "用户管理", None),
    ]
    specs.extend(
        ("doctor", f"演示医生{index:02d}", "心理科", "医师")
        for index in range(1, 6)
    )
    specs.extend(
        ("patient", f"演示患者{index:03d}", None, None)
        for index in range(1, 51)
    )

    next_values = dict(sequence_starts)
    users: list[BootstrapUser] = []
    for index, (role, name, department, title) in enumerate(specs, start=1):
        prefix = "A" if role in {"admin", "super_admin"} else ("D" if role == "doctor" else "P")
        value = next_values[prefix]
        next_values[prefix] += 1
        account = f"{prefix}{value:03d}"
        password = secrets.token_urlsafe(18)
        phone = str(18_890_000_000 + index)
        email = f"{account.casefold()}@example.invalid"
        birth_date = date(1980, 1, 1) + timedelta(days=index * 37)
        users.append(
            BootstrapUser(
                user_id=str(uuid.uuid4()),
                role=role,
                account=account,
                display_name=name,
                password=password,
                password_hash=password_hasher.hash_password(password),
                phone=phone,
                email=email,
                id_card=make_synthetic_id(index, birth_date),
                department=department,
                professional_title=title,
            )
        )
    return users


def write_pending_credentials(path: Path, users: list[BootstrapUser]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"凭据文件已存在，拒绝覆盖：{path}")
    pending_path = path.with_suffix(".pending.csv")
    if pending_path.exists():
        raise FileExistsError(f"存在未完成的凭据文件：{pending_path}")
    with pending_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "role",
                "account",
                "initial_password",
                "display_name",
                "phone",
                "email",
                "account_status",
                "must_change_password",
                "data_notice",
            ),
        )
        writer.writeheader()
        for user in users:
            writer.writerow(
                {
                    "role": user.role,
                    "account": user.account,
                    "initial_password": user.password,
                    "display_name": user.display_name,
                    "phone": user.phone,
                    "email": user.email,
                    "account_status": "active",
                    "must_change_password": 1,
                    "data_notice": "synthetic_demo_data",
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(pending_path, 0o600)
    return pending_path


def bootstrap_accounts(
    *,
    database_path: Path,
    credentials_path: Path,
    pepper_path: Path,
    password_iterations: int = 600_000,
    required_drive: str | None = "E:",
) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    if (
        required_drive
        and database_path.drive.upper() != required_drive.upper()
    ):
        raise ValueError(
            f"正式数据库必须位于 {required_drive}：{database_path}"
        )

    pepper = ensure_pepper(pepper_path)
    protector = IdentifierProtector(pepper)
    password_hasher = PasswordHasher(iterations=password_iterations)

    preflight = sqlite3.connect(database_path)
    try:
        preflight.row_factory = sqlite3.Row
        version = int(
            preflight.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_metadata"
            ).fetchone()[0]
        )
        if version < 3:
            raise RuntimeError("数据库 schema 版本低于 3，请先执行迁移")
        existing_users = int(preflight.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if existing_users:
            raise RuntimeError(f"数据库已有 {existing_users} 个用户，拒绝重复初始化")
        sequence_starts = {
            row["prefix"]: int(row["next_value"])
            for row in preflight.execute(
                "SELECT prefix, next_value FROM account_sequences"
            ).fetchall()
        }
    finally:
        preflight.close()

    if not {"A", "D", "P"}.issubset(sequence_starts):
        raise RuntimeError("账号序列不完整")
    users = build_users(sequence_starts, password_hasher)
    pending_credentials = write_pending_credentials(credentials_path, users)
    now = datetime.now(UTC).isoformat()
    super_admin_id = users[0].user_id

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise RuntimeError("初始化期间检测到其他用户写入，已中止")

        for user in users:
            connection.execute(
                """
                INSERT INTO users (
                    id, account, password_hash, display_name, role,
                    account_status, must_change_password, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    user.user_id,
                    user.account,
                    user.password_hash,
                    user.display_name,
                    user.role,
                    now,
                    now,
                ),
            )
            id_info = protector.parse_id_card(user.id_card)
            phone = protector.normalize_phone(user.phone)
            email = protector.normalize_email(user.email)
            connection.execute(
                """
                INSERT INTO person_profiles (
                    user_id, id_card_fingerprint, id_card_masked,
                    phone_masked, email_masked, birth_date, gender,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.user_id,
                    protector.fingerprint("id_card", user.id_card),
                    protector.mask("id_card", id_info.normalized),
                    protector.mask("phone", phone),
                    protector.mask("email", email),
                    id_info.birth_date.isoformat(),
                    id_info.gender,
                    now,
                    now,
                ),
            )
            identifiers = (
                ("account", user.account, user.account),
                ("phone", phone, protector.mask("phone", phone)),
                ("email", email, protector.mask("email", email)),
            )
            for kind, raw_value, masked in identifiers:
                connection.execute(
                    """
                    INSERT INTO user_login_identifiers (
                        id, user_id, identifier_type, identifier_fingerprint,
                        identifier_masked, verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        user.user_id,
                        kind,
                        protector.fingerprint(kind, raw_value),
                        masked,
                        now,
                    ),
                )

            if user.role in {"admin", "super_admin"}:
                connection.execute(
                    """
                    INSERT INTO admin_profiles (
                        user_id, employee_no, department, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (user.user_id, user.account, user.department, now, now),
                )
            elif user.role == "doctor":
                connection.execute(
                    """
                    INSERT INTO doctor_profiles (
                        user_id, employee_no, department, professional_title,
                        employment_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        user.user_id,
                        user.account,
                        user.department,
                        user.professional_title,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO registration_requests (
                        id, user_id, requested_role, status, department,
                        professional_title, submitted_at, reviewed_by,
                        reviewed_at, review_note
                    ) VALUES (?, ?, 'doctor', 'approved', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        user.user_id,
                        user.department,
                        user.professional_title,
                        now,
                        super_admin_id,
                        now,
                        "initial synthetic account bootstrap",
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO patient_profiles (
                        user_id, medical_record_no, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (user.user_id, user.account, now, now),
                )

        next_values = {
            "A": sequence_starts["A"] + 3,
            "D": sequence_starts["D"] + 5,
            "P": sequence_starts["P"] + 50,
        }
        if "S" in sequence_starts:
            next_values["S"] = sequence_starts["S"]
        connection.executemany(
            "UPDATE account_sequences SET next_value = ? WHERE prefix = ?",
            [(value, prefix) for prefix, value in next_values.items()],
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                id, actor_user_id, action, target_type,
                filters_json, result_count, status
            ) VALUES (?, ?, 'bootstrap.create_accounts', 'users', ?, 58, 'success')
            """,
            (
                str(uuid.uuid4()),
                super_admin_id,
                json.dumps(
                    {
                        "super_admin": 1,
                        "admin": 2,
                        "doctor": 5,
                        "patient": 50,
                        "synthetic": True,
                    }
                ),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    pending_credentials.replace(credentials_path)
    os.chmod(credentials_path, 0o600)
    return {
        "database_path": str(database_path),
        "credentials_path": str(credentials_path),
        "pepper_path": str(pepper_path),
        "counts": {"super_admin": 1, "admin": 2, "doctor": 5, "patient": 50},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="创建系统初始化合成账号")
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--credentials-path", type=Path, default=DEFAULT_CREDENTIALS_PATH)
    parser.add_argument("--pepper-path", type=Path, default=DEFAULT_PEPPER_PATH)
    parser.add_argument("--password-iterations", type=int, default=600_000)
    args = parser.parse_args()
    result = bootstrap_accounts(
        database_path=args.database_path,
        credentials_path=args.credentials_path,
        pepper_path=args.pepper_path,
        password_iterations=args.password_iterations,
        required_drive="E:",
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
