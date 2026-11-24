"""Compact, transport-safe error serialization (upstream error-formatter.ts)."""

import json
from collections.abc import Iterable
from typing import Any, NotRequired, TypedDict

MAX_SERIALIZED_STRING_LENGTH = 4096
_TRUNCATED_SUFFIX = "… [truncated]"


class SerializedError(TypedDict):
    name: str
    message: str
    stack: NotRequired[str]
    code: NotRequired[str | int | float]
    status: NotRequired[str | int | float]
    requestId: NotRequired[str | int | float]


class SerializedErrorResult(TypedDict):
    error: SerializedError
    hasMessage: bool


def truncate_serialized_error_string(value: str) -> str:
    if len(value) <= MAX_SERIALIZED_STRING_LENGTH:
        return value
    keep = MAX_SERIALIZED_STRING_LENGTH - len(_TRUNCATED_SUFFIX)
    return f"{value[:keep]}{_TRUNCATED_SUFFIX}"


def _is_object(value: Any) -> bool:
    return not isinstance(value, (str, int, float, bool, bytes, type(None)))


def _safely_read_property(value: Any, key: str) -> Any:
    try:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None


def _read_bounded_diagnostic(
    value: Any, keys: Iterable[str]
) -> str | int | float | None:
    for key in keys:
        diagnostic = _safely_read_property(value, key)
        if isinstance(diagnostic, bool):
            continue
        if isinstance(diagnostic, (int, float)):
            return diagnostic
        if isinstance(diagnostic, str):
            return truncate_serialized_error_string(diagnostic)
    return None


def _read_non_empty_message(value: Any) -> str | None:
    message = _safely_read_property(value, "message")
    if isinstance(message, str) and message:
        return message
    if isinstance(value, BaseException):
        text = str(value)
        return text or None
    return None


def _extract_string_message(value: Any) -> str | None:
    direct = _read_non_empty_message(value)
    if direct:
        return direct

    for nested_key in ("error", "cause", "__cause__"):
        nested = _safely_read_property(value, nested_key)
        if not _is_object(nested):
            continue
        nested_message = _read_non_empty_message(nested)
        if nested_message:
            return nested_message
    return None


def get_error_stack(error: Any) -> str | None:
    if not _is_object(error):
        return None
    stack = _safely_read_property(error, "stack")
    return stack if isinstance(stack, str) else None


def _serialize_error_value(error: Any) -> SerializedErrorResult:
    if not _is_object(error):
        message = truncate_serialized_error_string(str(error))
        return {
            "error": {
                "name": "NonError",
                "message": message if message.strip() else "Empty string thrown",
            },
            "hasMessage": bool(message.strip()),
        }

    name = _safely_read_property(error, "name")
    if not isinstance(name, str) or not name:
        name = type(error).__name__ if isinstance(error, BaseException) else "Error"
    serialized: SerializedError = {
        "name": truncate_serialized_error_string(name),
        "message": truncate_serialized_error_string(
            _extract_string_message(error) or f"{name} without a message"
        ),
    }

    stack = get_error_stack(error)
    if stack:
        serialized["stack"] = truncate_serialized_error_string(stack)

    code = _read_bounded_diagnostic(error, ["code"])
    status = _read_bounded_diagnostic(error, ["status", "statusCode", "status_code"])
    request_id = _read_bounded_diagnostic(
        error, ["requestId", "requestID", "request_id"]
    )
    if code is not None:
        serialized["code"] = code
    if status is not None:
        serialized["status"] = status
    if request_id is not None:
        serialized["requestId"] = request_id

    return {
        "error": serialized,
        "hasMessage": _extract_string_message(error) is not None,
    }


def get_error_message(error: Any) -> str:
    """Extract a human-readable message from an unknown thrown value."""
    result = _serialize_error_value(error)
    serialized = result["error"]
    if not _is_object(error) or result["hasMessage"]:
        return serialized["message"]

    summary: SerializedError = {
        "name": serialized["name"],
        "message": serialized["message"],
    }
    for key in ("code", "status", "requestId"):
        if key in serialized:
            summary[key] = serialized[key]
    return truncate_serialized_error_string(json.dumps(summary, ensure_ascii=False))


def serialize_error(error: Any) -> SerializedError:
    return _serialize_error_value(error)["error"]


__all__ = [
    "SerializedError",
    "get_error_message",
    "get_error_stack",
    "serialize_error",
    "truncate_serialized_error_string",
]
