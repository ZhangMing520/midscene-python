"""Locate result field readers (upstream shared/model-locate-result/result-field.ts)."""

from typing import Any, Dict, List


def locate_result_keys(prompt_spec: Dict[str, Any]) -> List[str]:
    return [prompt_spec["resultKey"], *prompt_spec.get("resultKeyAliases", [])]


def read_locate_result_field(
    record: Dict[str, Any], prompt_spec: Dict[str, Any], prefix: str = ""
) -> Any:
    """An explicit null or empty array takes precedence over any fallback field."""
    for key in locate_result_keys(prompt_spec):
        full_key = f"{prefix}{key}"
        if full_key in record and record[full_key] is not None:
            return record[full_key]
    return None
