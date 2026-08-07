from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.identifiers import IdentifierProtector  # noqa: E402
from app.core.passwords import PasswordHasher  # noqa: E402


DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
DEFAULT_CREDENTIALS_PATH = PROJECT_ROOT / "private" / "initial_accounts.csv"
DEFAULT_PEPPER_PATH = PROJECT_ROOT / "private" / "auth_pepper.key"


def verify_bootstrap(
    database_path: Path,
    credentials_path: Path,
    pepper_path: Path,
) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    if not credentials_path.is_file():
        raise FileNotFoundError(f"凭据文件不存在：{credentials_path}")
    pepper = pepper_path.read_bytes()
    protector = IdentifierProtector(pepper)
    hasher = PasswordHasher()

    with credentials_path.open(encoding="utf-8-sig", newline="") as handle:
        credentials = list(csv.DictReader(handle))
    if len(credentials) != 58:
        raise RuntimeError(f"凭据数量应为 58，实际为 {len(credentials)}")

    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        schema_version = connection.execute(
            "SELECT MAX(version) FROM schema_metadata"
        ).fetchone()[0]
        database_roles = dict(
            connection.execute(
                "SELECT role, COUNT(*) FROM users GROUP BY role"
            ).fetchall()
        )
        for credential in credentials:
            user = connection.execute(
                """
                SELECT id, password_hash, must_change_password
                FROM users WHERE account = ?
                """,
                (credential["account"],),
            ).fetchone()
            if not user:
                raise RuntimeError(f"凭据对应账号不存在：{credential['account']}")
            if not hasher.verify_password(
                credential["initial_password"], user["password_hash"]
            ):
                raise RuntimeError(f"密码哈希不匹配：{credential['account']}")
            if user["must_change_password"] != 1:
                raise RuntimeError(f"初始改密标记不正确：{credential['account']}")

            values = {
                "account": credential["account"],
                "phone": credential["phone"],
                "email": credential["email"],
            }
            for kind, value in values.items():
                fingerprint = protector.fingerprint(kind, value)
                match = connection.execute(
                    """
                    SELECT 1 FROM user_login_identifiers
                    WHERE user_id = ? AND identifier_type = ?
                      AND identifier_fingerprint = ?
                    """,
                    (user["id"], kind, fingerprint),
                ).fetchone()
                if not match:
                    raise RuntimeError(
                        f"登录标识指纹不匹配：{credential['account']} / {kind}"
                    )

        doctor_profiles = connection.execute(
            "SELECT COUNT(*) FROM doctor_profiles WHERE employment_status = 'active'"
        ).fetchone()[0]
        approved_doctors = connection.execute(
            "SELECT COUNT(*) FROM registration_requests WHERE status = 'approved'"
        ).fetchone()[0]
        patient_profiles = connection.execute(
            "SELECT COUNT(*) FROM patient_profiles"
        ).fetchone()[0]
        admin_profiles = connection.execute(
            "SELECT COUNT(*) FROM admin_profiles"
        ).fetchone()[0]
    finally:
        connection.close()

    expected_roles = {"super_admin": 1, "admin": 2, "doctor": 5, "patient": 50}
    credential_roles = dict(Counter(row["role"] for row in credentials))
    if integrity != "ok" or schema_version != 3:
        raise RuntimeError("数据库完整性或 schema 版本不正确")
    if database_roles != expected_roles or credential_roles != expected_roles:
        raise RuntimeError("数据库或凭据角色数量不正确")
    if (doctor_profiles, approved_doctors, patient_profiles, admin_profiles) != (
        5,
        5,
        50,
        3,
    ):
        raise RuntimeError("角色扩展档案数量不正确")

    return {
        "integrity_check": integrity,
        "schema_version": schema_version,
        "credential_count": len(credentials),
        "role_counts": database_roles,
        "password_hashes_verified": len(credentials),
        "login_identifier_sets_verified": len(credentials),
        "doctor_profiles_active": doctor_profiles,
        "doctor_registrations_approved": approved_doctors,
        "patient_profiles": patient_profiles,
        "admin_profiles": admin_profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="验证初始化账号和登录标识")
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--credentials-path", type=Path, default=DEFAULT_CREDENTIALS_PATH)
    parser.add_argument("--pepper-path", type=Path, default=DEFAULT_PEPPER_PATH)
    args = parser.parse_args()
    result = verify_bootstrap(
        args.database_path,
        args.credentials_path,
        args.pepper_path,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
