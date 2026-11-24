"""Core errors (upstream packages/core/src/errors.ts)."""

from typing import Any


class LocateFailureError(Exception):
    """Raised when the model cannot locate the requested element."""


class ServiceError(Exception):
    """An AI service call failed; carries the partial service dump."""

    def __init__(self, message: str, dump: dict[str, Any]) -> None:
        super().__init__(message)
        self.name = "ServiceError"
        self.dump = dump


__all__ = ["LocateFailureError", "ServiceError"]
