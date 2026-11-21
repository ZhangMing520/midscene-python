"""Internal-only helpers for CLI argument key aliasing (upstream key-alias-utils).

Not re-exported from the package entry point - keep consumers within
``midscene.shared``.
"""

import re
from typing import Any, List

_KEBAB_TO_CAMEL = re.compile(r"-([a-z])")
_CAMEL_TO_KEBAB = re.compile(r"[A-Z]")


def kebab_to_camel(value: str) -> str:
    return _KEBAB_TO_CAMEL.sub(lambda match: match.group(1).upper(), value)


def camel_to_kebab(value: str) -> str:
    result = _CAMEL_TO_KEBAB.sub(lambda match: f"-{match.group(0).lower()}", value)
    return result[1:] if result.startswith("-") else result


def get_key_aliases(key: str) -> List[str]:
    aliases: List[str] = [key, kebab_to_camel(key), camel_to_kebab(key)]
    return list(dict.fromkeys(aliases))


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


__all__ = [
    "camel_to_kebab",
    "get_key_aliases",
    "is_record",
    "kebab_to_camel",
]
