"""Bounded, JSON-safe report values (upstream test-runner/reporting/sanitize.ts)."""

import datetime
import json
import re
from typing import Any, Literal

from midscene.core.test_run_report import TestRunReportError, TestRunReportValue

MAX_DEPTH = 6
MAX_STRING_LENGTH = 2_000
MAX_ARRAY_ITEMS = 50
MAX_OBJECT_KEYS = 50
MAX_SERIALIZED_BYTES = 64 * 1024
TRUNCATED_VALUE = "[Truncated: display value exceeded 64 KiB]"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def _object_path(parent: str, key: str) -> str:
    if _IDENTIFIER_RE.match(key):
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key)}]"


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def sanitize_report_text(value: str, maximum_length: int = MAX_STRING_LENGTH) -> str:
    if len(value) <= maximum_length:
        return value
    return f"{value[:maximum_length]}… [truncated]"


def sanitize_report_value(value: Any) -> TestRunReportValue:
    """Convert arbitrary node input/output to a bounded, JSON-safe value."""
    truncated_paths: set[str] = set()
    ancestors: set[int] = set()
    remaining = [MAX_SERIALIZED_BYTES]

    def consume(path: str, text: str) -> bool:
        remaining[0] -= _byte_length(text)
        if remaining[0] >= 0:
            return True
        truncated_paths.add(path)
        return False

    def visit(current: Any, path: str, depth: int) -> Any:
        if remaining[0] <= 0:
            truncated_paths.add(path)
            return "[Truncated: size limit]"
        if current is None or isinstance(current, bool):
            consume(path, str(current))
            return current
        if isinstance(current, str):
            if len(current) > MAX_STRING_LENGTH:
                truncated_paths.add(path)
                shortened = f"{current[:MAX_STRING_LENGTH]}… [truncated]"
                consume(path, shortened)
                return shortened
            consume(path, current)
            return current
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            if isinstance(current, float) and (
                current != current or current in (float("inf"), float("-inf"))
            ):
                truncated_paths.add(path)
                return f"[Unsupported number: {current}]"
            consume(path, str(current))
            return current
        if isinstance(current, (bytes, bytearray)):
            truncated_paths.add(path)
            return "[Unsupported bytes]"
        if current is ...:
            truncated_paths.add(path)
            return "[Unsupported ellipsis]"
        if depth >= MAX_DEPTH:
            truncated_paths.add(path)
            return "[Truncated: maximum depth]"
        if isinstance(current, datetime.datetime):
            date = current.isoformat()
            consume(path, date)
            return date
        if isinstance(current, (dict, list, tuple, set)):
            marker = id(current)
            if marker in ancestors:
                truncated_paths.add(path)
                return "[Unsupported circular value]"
            ancestors.add(marker)
            try:
                if isinstance(current, (list, tuple)):
                    output: list[Any] = []
                    item_count = min(len(current), MAX_ARRAY_ITEMS)
                    for index in range(item_count):
                        if remaining[0] <= 0:
                            break
                        output.append(
                            visit(current[index], f"{path}[{index}]", depth + 1)
                        )
                    if len(current) > len(output):
                        truncated_paths.add(path)
                    return output
                if isinstance(current, set):
                    truncated_paths.add(path)
                    return f"[Unsupported object: {type(current).__name__}]"
                output_dict: dict[str, Any] = {}
                keys = list(current.keys())
                for key in keys[:MAX_OBJECT_KEYS]:
                    key_text = str(key)
                    child_path = _object_path(path, key_text)
                    if not consume(child_path, key_text):
                        break
                    output_dict[key_text] = visit(current[key], child_path, depth + 1)
                    if remaining[0] <= 0:
                        break
                if len(keys) > len(output_dict):
                    truncated_paths.add(path)
                return output_dict
            finally:
                ancestors.discard(marker)
        truncated_paths.add(path)
        return f"[Unsupported object: {type(current).__name__}]"

    sanitized = visit(value, "$", 0)
    try:
        serialized = json.dumps(sanitized, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"value": TRUNCATED_VALUE, "truncatedPaths": ["$"]}
    if _byte_length(serialized) > MAX_SERIALIZED_BYTES:
        return {"value": TRUNCATED_VALUE, "truncatedPaths": ["$"]}

    result: TestRunReportValue = {"value": sanitized}
    if truncated_paths:
        result["truncatedPaths"] = list(truncated_paths)
    return result


def _error_attr(error: Any, name: str) -> Any:
    if isinstance(error, dict):
        return error.get(name)
    return getattr(error, name, None)


def sanitize_report_error(error: Any) -> TestRunReportError:
    ancestors: set[int] = set()
    remaining = [MAX_SERIALIZED_BYTES - 1024]
    nodes = [0]

    def shortened() -> TestRunReportError:
        return {
            "format": "midscene-error",
            "name": "Error",
            "message": "[Truncated: error cause chain]",
            "truncated": True,
        }

    def visit(current: Any, depth: int) -> TestRunReportError:
        if depth >= MAX_DEPTH or nodes[0] >= 25 or remaining[0] < 4096:
            nodes[0] += 1
            return shortened()
        nodes[0] += 1
        if not isinstance(current, (BaseException, dict)) and not hasattr(
            current, "__dict__"
        ):
            return {
                "format": "midscene-error",
                "name": "Error",
                "message": sanitize_report_text(str(current)),
            }
        marker = id(current)
        if marker in ancestors:
            return shortened()
        ancestors.add(marker)
        try:
            truncated = _error_attr(current, "truncated") is True
            name_value = _error_attr(current, "name")
            message_value = _error_attr(current, "message")
            result: TestRunReportError = {
                "format": "midscene-error",
                "name": sanitize_report_text(
                    name_value
                    if isinstance(name_value, str)
                    else type(current).__name__,
                    200,
                ),
                "message": sanitize_report_text(
                    message_value if isinstance(message_value, str) else str(current)
                ),
            }
            if truncated:
                result["truncated"] = True
            code = _error_attr(current, "code")
            if isinstance(code, str):
                result["code"] = sanitize_report_text(code, 200)
            remaining[0] -= (
                _byte_length(json.dumps(result, ensure_ascii=False, default=str)) + 128
            )

            details_value = _error_attr(current, "details")
            if details_value is not None:
                encoded = None
                if (
                    _error_attr(current, "format") == "midscene-error"
                    and isinstance(details_value, dict)
                    and "value" in details_value
                ):
                    encoded = details_value
                details = sanitize_report_value(
                    encoded["value"] if encoded is not None else details_value
                )
                path_fields: tuple[Literal["redactedPaths", "truncatedPaths"], ...] = (
                    "redactedPaths",
                    "truncatedPaths",
                )
                for field in path_fields:
                    paths = encoded.get(field) if encoded is not None else None
                    if isinstance(paths, list):
                        merged = list(details.get(field) or [])
                        for path in paths:
                            if isinstance(path, str):
                                text = sanitize_report_text(path)
                                if text not in merged:
                                    merged.append(text)
                        details[field] = merged[:50]
                bytes_used = _byte_length(
                    json.dumps(details, ensure_ascii=False, default=str)
                )
                if bytes_used < remaining[0] - 4096:
                    result["details"] = details
                    remaining[0] -= bytes_used
                else:
                    result["details"] = {
                        "value": "[Truncated: error details size limit]",
                        "truncatedPaths": ["$"],
                    }
                    result["truncated"] = True

            cause = _error_attr(current, "cause")
            if cause is not None:
                result["cause"] = visit(cause, depth + 1)
            nested_errors = _error_attr(current, "errors")
            if isinstance(nested_errors, (list, tuple)):
                collected: list[TestRunReportError] = []
                for item in list(nested_errors)[:10]:
                    if nodes[0] >= 25 or remaining[0] < 4096:
                        result["truncated"] = True
                        break
                    collected.append(visit(item, depth + 1))
                result["errors"] = collected
                if len(collected) < len(nested_errors):
                    result["truncated"] = True

            stack = _error_attr(current, "stack")
            if isinstance(stack, str) and stack:
                budget = max(0, remaining[0] - 128)
                if _byte_length(json.dumps(stack)) > budget:
                    suffix = "\n… [truncated: stack trace size limit]"
                    low, high = 0, len(stack)
                    while low < high:
                        middle = (low + high + 1) // 2
                        candidate = stack[:middle] + suffix
                        if _byte_length(json.dumps(candidate)) <= budget:
                            low = middle
                        else:
                            high = middle - 1
                    stack = stack[:low] + suffix if low else ""
                    result["truncated"] = True
                if stack:
                    result["stack"] = stack
                    remaining[0] -= _byte_length(json.dumps(stack))
            return result
        finally:
            ancestors.discard(marker)

    result = visit(error, 0)
    if (
        _byte_length(json.dumps(result, ensure_ascii=False, default=str))
        <= MAX_SERIALIZED_BYTES
    ):
        return result
    return {
        "format": "midscene-error",
        "name": result.get("name", "Error"),
        "message": result.get("message", ""),
        **({"code": result["code"]} if result.get("code") else {}),
        "truncated": True,
        "cause": {
            "format": "midscene-error",
            "name": "Error",
            "message": "[Truncated: serialized error exceeded 64 KiB]",
            "truncated": True,
        },
    }


__all__ = [
    "MAX_SERIALIZED_BYTES",
    "TRUNCATED_VALUE",
    "sanitize_report_error",
    "sanitize_report_text",
    "sanitize_report_value",
]
