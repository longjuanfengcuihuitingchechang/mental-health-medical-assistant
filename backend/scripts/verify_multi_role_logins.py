from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.container import build_application_agents  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.schemas.login import IdentityType, LoginRequest  # noqa: E402


DEFAULT_DATABASE_PATH = Path(r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db")
DEFAULT_INITIAL_CREDENTIALS = PROJECT_ROOT / "private" / "initial_accounts.csv"
DEFAULT_ASSISTANT_CREDENTIALS = PROJECT_ROOT / "private" / "assistant_accounts.csv"
DEFAULT_PEPPER_PATH = PROJECT_ROOT / "private" / "auth_pepper.key"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify(
    *,
    database_path: Path,
    initial_credentials: Path,
    assistant_credentials: Path,
    pepper_path: Path,
) -> dict:
    initial = _rows(initial_credentials)
    assistants = _rows(assistant_credentials)
    selected = [
        (IdentityType.PATIENT, next(row for row in initial if row["role"] == "patient")),
        (IdentityType.DOCTOR, next(row for row in initial if row["role"] == "doctor")),
        (IdentityType.ASSISTANT, assistants[0]),
    ]
    agents = build_application_agents(
        Settings(
            database_path=database_path,
            required_drive=database_path.drive,
            auth_pepper_file=pepper_path,
        )
    )
    requests = [
        LoginRequest(identity, row["account"], row["initial_password"])
        for identity, row in selected
    ]
    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(agents.login.run, requests))
    if not all(response.success for response in responses):
        raise RuntimeError("多角色并发登录验证失败")
    tokens = {response.session_token for response in responses}
    if len(tokens) != 3:
        raise RuntimeError("并发登录会话未隔离")
    return {
        "parallel_logins": len(responses),
        "roles": sorted(response.role.value for response in responses),
        "redirect_paths": sorted(response.redirect_path for response in responses),
        "unique_sessions": len(tokens),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="并发验证患者、医生、助理登录与会话隔离")
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--initial-credentials", type=Path, default=DEFAULT_INITIAL_CREDENTIALS)
    parser.add_argument("--assistant-credentials", type=Path, default=DEFAULT_ASSISTANT_CREDENTIALS)
    parser.add_argument("--pepper-path", type=Path, default=DEFAULT_PEPPER_PATH)
    args = parser.parse_args()
    result = verify(
        database_path=args.database_path,
        initial_credentials=args.initial_credentials,
        assistant_credentials=args.assistant_credentials,
        pepper_path=args.pepper_path,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
