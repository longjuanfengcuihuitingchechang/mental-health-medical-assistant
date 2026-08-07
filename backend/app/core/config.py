from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_DATABASE_PATH = Path(
    r"E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db"
)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUTH_PEPPER_FILE = PROJECT_ROOT / "private" / "auth_pepper.key"
DEFAULT_DOTENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))
    required_drive: str | None = os.getenv("DATABASE_REQUIRED_DRIVE", "E:")
    auth_pepper_file: Path = Path(
        os.getenv("AUTH_PEPPER_FILE", str(DEFAULT_AUTH_PEPPER_FILE))
    )
    login_max_attempts: int = 8
    login_lock_minutes: int = 5
    session_hours: int = 8
    password_pbkdf2_iterations: int = 600_000
    dotenv_file: Path = DEFAULT_DOTENV_FILE
    deepseek_base_url: str = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    )
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_timeout_seconds: float = float(
        os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20")
    )
    agent_task_timeout_seconds: float = float(
        os.getenv("AGENT_TASK_TIMEOUT_SECONDS", "30")
    )
    agent_task_workers: int = int(os.getenv("AGENT_TASK_WORKERS", "4"))
    app_env: str = os.getenv("APP_ENV", "development")
    session_cookie_secure: bool = os.getenv(
        "SESSION_COOKIE_SECURE", "false"
    ).lower() in {"1", "true", "yes"}
    static_files_path: Path = Path(
        os.getenv("STATIC_FILES_PATH", str(PROJECT_ROOT / "fronts"))
    )
    cors_allowed_origins_raw: str = os.getenv("CORS_ALLOWED_ORIGINS", "")
    allowed_hosts_raw: str = os.getenv(
        "ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
    )
    max_request_body_bytes: int = int(os.getenv("MAX_REQUEST_BODY_BYTES", "65536"))
    login_ip_limit: int = int(os.getenv("LOGIN_IP_LIMIT", "30"))
    login_account_limit: int = int(os.getenv("LOGIN_ACCOUNT_LIMIT", "12"))
    login_rate_window_seconds: int = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300"))
    assistant_user_limit: int = int(os.getenv("ASSISTANT_USER_LIMIT", "20"))
    assistant_rate_window_seconds: int = int(os.getenv("ASSISTANT_RATE_WINDOW_SECONDS", "60"))

    def validated_database_path(self) -> Path:
        path = self.database_path.expanduser()
        if not path.is_absolute():
            raise ValueError("DATABASE_PATH 必须是绝对路径")

        required_drive = (
            self.required_drive.rstrip("\\/").upper()
            if self.required_drive
            else None
        )
        if required_drive and path.drive.upper() != required_drive:
            raise ValueError(
                f"数据库必须位于 {required_drive}，当前路径为 {path}"
            )
        return path

    def load_auth_pepper(self) -> bytes:
        path = self.auth_pepper_file.expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"认证 pepper 文件不存在：{path}")
        secret = path.read_bytes()
        if len(secret) < 32:
            raise ValueError("认证 pepper 长度不能少于 32 字节")
        return secret

    def load_deepseek_api_key(self, *, required: bool = False) -> str | None:
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            key = _read_dotenv_value(self.dotenv_file, "DEEPSEEK_API_KEY")
        key = key.strip() if key else None
        if required and not key:
            raise ValueError("未配置 DEEPSEEK_API_KEY")
        return key

    def cors_allowed_origins(self) -> tuple[str, ...]:
        origins = tuple(
            item.strip().rstrip("/")
            for item in self.cors_allowed_origins_raw.split(",")
            if item.strip()
        )
        if "*" in origins:
            raise ValueError("携带凭据时禁止使用通配 CORS Origin")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
                raise ValueError(f"CORS Origin 不合法：{origin}")
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("生产环境 CORS Origin 必须使用 HTTPS")
        return origins

    def validate_security(self) -> None:
        if self.max_request_body_bytes < 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES 不能小于 1024")
        limits = (
            self.login_ip_limit,
            self.login_account_limit,
            self.login_rate_window_seconds,
            self.assistant_user_limit,
            self.assistant_rate_window_seconds,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("安全限流配置必须为正整数")
        if self.app_env == "production" and not self.session_cookie_secure:
            raise ValueError("生产环境必须启用 SESSION_COOKIE_SECURE")
        self.allowed_hosts()
        self.cors_allowed_origins()

    def allowed_hosts(self) -> tuple[str, ...]:
        hosts = tuple(
            item.strip().lower()
            for item in self.allowed_hosts_raw.split(",")
            if item.strip()
        )
        if not hosts:
            raise ValueError("ALLOWED_HOSTS 不能为空")
        for host in hosts:
            if host == "*" or "://" in host or "/" in host or any(char.isspace() for char in host):
                raise ValueError(f"ALLOWED_HOSTS 主机名不合法：{host}")
        return hosts


def _read_dotenv_value(path: Path, key: str) -> str | None:
    """只读一个 dotenv 键；不修改文件、不展开变量。"""
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == key:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None


settings = Settings()
