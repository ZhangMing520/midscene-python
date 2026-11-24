"""Locate result field readers (upstream shared/model-locate-result/result-field.ts)."""

from typing import Any


def locate_result_keys(prompt_spec: dict[str, Any]) -> list[str]:
    return [prompt_spec["resultKey"], *prompt_spec.get("resultKeyAliases", [])]


def read_locate_result_field(
    record: dict[str, Any], prompt_spec: dict[str, Any], prefix: str = ""
) -> Any:
    """An explicit null or empty array takes precedence over any fallback field."""
    for key in locate_result_keys(prompt_spec):
        full_key = f"{prefix}{key}"
        if full_key in record and record[full_key] is not None:
            return record[full_key]
    return None
