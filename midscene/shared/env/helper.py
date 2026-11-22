"""Env config helpers (upstream packages/shared/src/env/helper.ts)."""

import json
from typing import Any, Dict, Optional


def mask_key(key: str, mask_char: str = "*") -> str:
    """Mask the middle of an API key, keeping three leading/trailing chars."""
    if not isinstance(key, str) or not key:
        return key

    prefix_len = 3
    suffix_len = 3
    keep_length = prefix_len + suffix_len
    if len(key) <= keep_length:
        return key

    prefix = key[:prefix_len]
    suffix = key[-suffix_len:]
    return f"{prefix}{mask_char * (len(key) - keep_length)}{suffix}"


def mask_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Mask every key-like value in a config mapping (upstream maskConfig)."""
    result: Dict[str, Any] = {}
    for key, value in config.items():
        if not value:
            result[key] = value
            continue
        if isinstance(value, str) and "key" in key.lower():
            result[key] = mask_key(value)
            continue
        if isinstance(value, dict):
            value_string = json.dumps(value, ensure_ascii=False)
            if "key" in value_string.lower():
                result[key] = mask_key(value_string)
                continue
        result[key] = value
    return result


def parse_json(key: str, value: Optional[str]) -> Any:
    """Parse a JSON env value, raising a descriptive error on bad input."""
    if value:
        try:
            return json.loads(value)
        except Exception as error:  # noqa: BLE001 - mirror upstream message
            raise ValueError(
                f"Failed to parse {key} as a JSON. {error}"
            ) from error
    return None


__all__ = ["mask_config", "mask_key", "parse_json"]
