from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import date, datetime


PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
ID_CARD_PATTERN = re.compile(r"^\d{17}[0-9X]$")
ID_CARD_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CARD_CHECK_CODES = "10X98765432"


@dataclass(frozen=True, slots=True)
class IdentityCardInfo:
    normalized: str
    birth_date: date
    gender: str


class IdentifierProtector:
    def __init__(self, pepper: bytes):
        if len(pepper) < 32:
            raise ValueError("pepper 长度不能少于 32 字节")
        self.pepper = pepper

    def fingerprint(self, kind: str, value: str) -> str:
        normalized = self.normalize(kind, value)
        material = f"{kind}\0{normalized}".encode("utf-8")
        return hmac.new(self.pepper, material, hashlib.sha256).hexdigest()

    def detect_login_kind(self, value: str) -> str:
        stripped = value.strip()
        if "@" in stripped:
            self.normalize_email(stripped)
            return "email"
        if re.fullmatch(r"\d{11}", stripped):
            self.normalize_phone(stripped)
            return "phone"
        self.normalize_account(stripped)
        return "account"

    def normalize(self, kind: str, value: str) -> str:
        normalizers = {
            "account": self.normalize_account,
            "phone": self.normalize_phone,
            "email": self.normalize_email,
            "id_card": lambda raw: self.parse_id_card(raw).normalized,
        }
        try:
            return normalizers[kind](value)
        except KeyError as exc:
            raise ValueError(f"不支持的标识类型：{kind}") from exc

    @staticmethod
    def normalize_account(value: str) -> str:
        normalized = value.strip().casefold()
        if not 1 <= len(normalized) <= 100:
            raise ValueError("账号长度必须在 1 到 100 之间")
        return normalized

    @staticmethod
    def normalize_phone(value: str) -> str:
        normalized = re.sub(r"[\s-]", "", value)
        if not PHONE_PATTERN.fullmatch(normalized):
            raise ValueError("手机号格式不正确")
        return normalized

    @staticmethod
    def normalize_email(value: str) -> str:
        normalized = value.strip().casefold()
        if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("邮箱格式不正确")
        return normalized

    @staticmethod
    def parse_id_card(value: str) -> IdentityCardInfo:
        normalized = value.strip().upper()
        if not ID_CARD_PATTERN.fullmatch(normalized):
            raise ValueError("身份证号格式不正确")
        total = sum(int(number) * weight for number, weight in zip(normalized[:17], ID_CARD_WEIGHTS))
        if ID_CARD_CHECK_CODES[total % 11] != normalized[-1]:
            raise ValueError("身份证号校验位不正确")
        try:
            birth_date = datetime.strptime(normalized[6:14], "%Y%m%d").date()
        except ValueError as exc:
            raise ValueError("身份证出生日期不正确") from exc
        if birth_date > date.today():
            raise ValueError("身份证出生日期不能晚于今天")
        gender = "male" if int(normalized[16]) % 2 else "female"
        return IdentityCardInfo(normalized, birth_date, gender)

    @staticmethod
    def mask(kind: str, normalized: str) -> str:
        if kind == "phone":
            return f"{normalized[:3]}****{normalized[-4:]}"
        if kind == "email":
            local, domain = normalized.split("@", 1)
            return f"{local[:1]}***@{domain}"
        if kind == "id_card":
            return f"{normalized[:6]}********{normalized[-4:]}"
        if kind == "account":
            return normalized
        raise ValueError(f"不支持的标识类型：{kind}")
