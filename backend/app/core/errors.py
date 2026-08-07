from __future__ import annotations


class APIError(Exception):
    def __init__(self, status_code: int, code: int, error: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.error = error
        self.message = message
        self.data: dict = {}
        self.headers: dict[str, str] = {}
