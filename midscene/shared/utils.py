"""Shared helpers (upstream packages/shared/src/utils.ts)."""

import hashlib
import json
import re
import uuid as _uuid_module
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

_UNSET = object()

# Upstream detects browser/worker/node globals.  The Python SDK runs in a
# node-like server process: there is no ``window`` or ``WorkerGlobalScope``.
if_in_browser = False
if_in_worker = False
if_in_node = True


def uuid() -> str:
    """Return a random UUID v4 string (upstream uuid)."""
    return str(_uuid_module.uuid4())


def sha256_hex(value: str) -> str:
    """SHA-256 hex digest of ``value`` (upstream sha256Hex)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_hash_map: Dict[str, str] = {}  # id - combined


def _to_js_json_value(value: Any) -> Any:
    """Normalize Python values to match ``JSON.stringify`` output.

    JavaScript serializes integral doubles without a trailing ``.0``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _to_js_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_js_json_value(item) for item in value]
    return value


def generate_hash_id(rect: Any, content: str = "") -> str:
    """Generate a short collision-resistant id from a rect and content.

    Mirrors upstream generateHashId: SHA-256 over ``JSON.stringify({content,
    rect})``, mapped to a-z, then sliced until the id is unique.
    """
    combined = json.dumps(
        {"content": content, "rect": _to_js_json_value(rect)},
        separators=(",", ":"),
        ensure_ascii=False,
    )

    slice_length = 5
    sliced_hash = ""
    hash_hex = hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def to_letters(hex_value: str) -> str:
        return "".join(
            chr(97 + int(char, 16) % 26) for char in hex_value
        )

    hash_letters = to_letters(hash_hex)

    while slice_length < len(hash_letters) - 1:
        sliced_hash = hash_letters[:slice_length]
        if sliced_hash in _hash_map and _hash_map[sliced_hash] != combined:
            slice_length += 1
            continue
        _hash_map[sliced_hash] = combined
        break
    return sliced_hash


def assert_(condition: Any, message: Optional[str] = None) -> None:
    """Raise when ``condition`` is falsy (upstream assert).

    ``assert`` is a Python keyword, so the function is exposed as ``assert_``
    and also registered under the upstream name on the module.
    """
    if not condition:
        raise AssertionError(message or "Assertion failed")


def log_msg(message: Any = _UNSET, *messages: Any) -> None:
    """Log to stdout (upstream logMsg)."""
    parts = ([] if message is _UNSET else [message]) + list(messages)
    print(*parts)


async def repeat(times: int, fn: Callable[[int], Awaitable[None]]) -> None:
    """Await ``fn`` ``times`` times with the current index (upstream repeat)."""
    for index in range(times):
        await fn(index)


_LT_PATTERN = re.compile(r"<")
_GT_PATTERN = re.compile(r">")
_LT_ESCAPE = "__midscene_lt__"
_GT_ESCAPE = "__midscene_gt__"


def escape_script_tag(html: str) -> str:
    """Escape ``<``/``>`` so inline scripts cannot break out (upstream)."""
    return _LT_PATTERN.sub(_LT_ESCAPE, _GT_PATTERN.sub(_GT_ESCAPE, html))


def anti_escape_script_tag(html: str) -> str:
    """Undo :func:`escape_script_tag` (upstream antiEscapeScriptTag)."""
    return html.replace(_LT_ESCAPE, "<").replace(_GT_ESCAPE, ">")


_ILLEGAL_PATH_CHARS = re.compile(r'[:*?"<>|# ]')


def replace_illegal_path_chars_and_space(value: str) -> str:
    """Replace filename-illegal characters and spaces with dashes (upstream)."""
    return _ILLEGAL_PATH_CHARS.sub("-", value)


def is_plain_object(value: Any) -> bool:
    """True for a non-null, non-array plain object (upstream isPlainObject)."""
    return isinstance(value, dict)


def normalize_for_comparison(value: str) -> str:
    """Normalize an app name for case-insensitive matching (upstream
    normalizeForComparison): lowercase and strip spaces, dashes, underscores."""
    return re.sub(r"[\s\-_]+", "", value.lower())


def merge_and_normalize_app_name_mapping(
    default_mapping: Mapping[str, str],
    user_mapping: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Merge app name mappings with normalized keys; user entries win.

    Matches upstream mergeAndNormalizeAppNameMapping.
    """
    result = {normalize_for_comparison(key): value for key, value in default_mapping.items()}
    if user_mapping:
        result.update(
            {normalize_for_comparison(key): value for key, value in user_mapping.items()}
        )
    return result


# The upstream helper is literally named ``assert``; Python keywords cannot be
# declared as function names, so expose the same attribute dynamically.
globals()["assert"] = assert_


__all__ = [
    "assert_",
    "escape_script_tag",
    "anti_escape_script_tag",
    "generate_hash_id",
    "if_in_browser",
    "if_in_node",
    "if_in_worker",
    "is_plain_object",
    "log_msg",
    "merge_and_normalize_app_name_mapping",
    "normalize_for_comparison",
    "repeat",
    "replace_illegal_path_chars_and_space",
    "sha256_hex",
    "uuid",
]
