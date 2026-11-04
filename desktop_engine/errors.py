"""Protocol error type and mapping from the shared desktop_review errors."""
from __future__ import annotations

CODES = {"bad_request", "not_signed_in", "not_found", "conflict",
         "confirmation_required", "auth_failed", "unavailable", "internal"}

_STATUS = {400: "bad_request", 401: "not_signed_in", 403: "confirmation_required",
           404: "not_found", 409: "conflict", 503: "unavailable"}


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        if code not in CODES:
            code = "internal"
        self.code = code
        super().__init__(message)

    def to_json(self) -> dict:
        return {"code": self.code, "message": str(self)}


def from_review(exc) -> EngineError:
    return EngineError(_STATUS.get(getattr(exc, "status", 500), "internal"), str(exc))
