from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MusicError(Exception):
    code: str
    message: str

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error_code": self.code,
            "message": self.message,
        }


def invalid_argument(message: str) -> MusicError:
    return MusicError("INVALID_ARGUMENT", message)