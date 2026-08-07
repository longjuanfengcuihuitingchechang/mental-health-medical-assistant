from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata


class PasswordHasher:
    algorithm = "pbkdf2_sha256"

    def __init__(self, iterations: int = 600_000, salt_bytes: int = 16):
        if iterations < 1_000:
            raise ValueError("PBKDF2 iterations 不能小于 1000")
        self.iterations = iterations
        self.salt_bytes = salt_bytes

    def hash_password(self, password: str) -> str:
        normalized = self._normalize(password)
        salt = secrets.token_bytes(self.salt_bytes)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            normalized,
            salt,
            self.iterations,
        )
        return "$".join(
            (
                self.algorithm,
                str(self.iterations),
                self._encode(salt),
                self._encode(digest),
            )
        )

    def verify_password(self, password: str, encoded_hash: str | None) -> bool:
        try:
            algorithm, iterations_text, salt_text, digest_text = (
                encoded_hash or ""
            ).split("$", 3)
            if algorithm != self.algorithm:
                return False
            iterations = int(iterations_text)
            salt = self._decode(salt_text)
            expected = self._decode(digest_text)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                self._normalize(password),
                salt,
                iterations,
                dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _normalize(password: str) -> bytes:
        if not isinstance(password, str):
            raise TypeError("password 必须是字符串")
        return unicodedata.normalize("NFC", password).encode("utf-8")

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)
