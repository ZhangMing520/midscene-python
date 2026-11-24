"""Normalize authored steps (upstream parser/normalize.ts)."""

from collections.abc import Callable
from typing import Any

from midscene.core.test_runner.errors import WorkflowParseError

_SUPPORTED_META_KEYS = {"timeout", "continue-on-error"}


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _format_step(index: int) -> str:
    return f"step {index + 1}"


def _normalize_meta(value: Any, index: int) -> dict[str, Any]:
    if value is None:
        return {"continueOnError": False}
    if not _is_mapping(value):
        raise WorkflowParseError(
            f'{_format_step(index)} "$" must be a mapping.', {"index": index}
        )
    for key in value:
        if key not in _SUPPORTED_META_KEYS:
            raise WorkflowParseError(
                f'{_format_step(index)} has unsupported engine metadata "{key}".',
                {"index": index, "key": key},
            )
    timeout = value.get("timeout")
    if timeout is not None and (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise WorkflowParseError(
            f'{_format_step(index)} "$.timeout" must be a positive number of milliseconds.',
            {"index": index, "timeout": timeout},
        )
    continue_on_error = value.get("continue-on-error")
    if continue_on_error is not None and not isinstance(continue_on_error, bool):
        raise WorkflowParseError(
            f'{_format_step(index)} "$.continue-on-error" must be a boolean.',
            {"index": index, "continueOnError": continue_on_error},
        )
    meta: dict[str, Any] = {"continueOnError": continue_on_error or False}
    if timeout is not None:
        meta["timeoutMs"] = timeout
    return meta


def normalize_step(
    value: Any,
    index: int = 0,
    resolve_node: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    if not _is_mapping(value):
        raise WorkflowParseError(
            f"{_format_step(index)} must be a mapping.", {"index": index}
        )
    entries = list(value.items())
    if len(entries) != 1:
        raise WorkflowParseError(
            f"{_format_step(index)} must contain exactly one node.",
            {"index": index, "nodes": list(value.keys())},
        )
    node, raw_value = entries[0]
    if not str(node).strip():
        raise WorkflowParseError(
            f"{_format_step(index)} node name must not be empty.", {"index": index}
        )
    if isinstance(raw_value, str):
        definition = resolve_node(node) if resolve_node else None
        string_input_key = definition.get("stringInputKey") if definition else "prompt"
        if string_input_key is False or string_input_key is None:
            raise WorkflowParseError(
                f'{_format_step(index)} node "{node}" does not accept string shorthand.',
                {"index": index, "node": node},
            )
        return {
            "node": node,
            "input": {string_input_key: raw_value},
            "meta": {"continueOnError": False},
        }
    if not _is_mapping(raw_value):
        raise WorkflowParseError(
            f"{_format_step(index)} value must be a string shorthand or a mapping.",
            {"index": index, "node": node},
        )
    raw_meta = raw_value.get("$")
    input_value = {key: item for key, item in raw_value.items() if key != "$"}
    return {
        "node": node,
        "input": input_value,
        "meta": _normalize_meta(raw_meta, index),
    }


def normalize_steps(
    steps: Any,
    resolve_node: Callable[[str], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        raise WorkflowParseError("Steps must be an array.")
    return [
        normalize_step(step, index, resolve_node) for index, step in enumerate(steps)
    ]
