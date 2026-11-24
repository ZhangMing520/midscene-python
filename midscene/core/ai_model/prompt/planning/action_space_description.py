"""Action space description (upstream prompt/planning/action-space-description.ts)."""

from collections.abc import Sequence
from typing import Any, Protocol

import yaml

from midscene.core.ai_model.model_adapter.planning_protocol import (
    StandardPlanningProtocol,
)
from midscene.core.ai_model.prompt.planning.action_output_example import (
    build_action_output_example,
)


class _LiteralBlockDumper(yaml.SafeDumper):
    """Dump multiline strings as literal blocks, matching js-yaml output."""


class _YamlDumper(Protocol):
    def represent_scalar(
        self, tag: str, value: str, style: str | None = None
    ) -> Any: ...


def _represent_str_as_literal(dumper: _YamlDumper, data: str) -> Any:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LiteralBlockDumper.add_representer(str, _represent_str_as_literal)


def _strip_undefined(value: Any) -> Any:
    """Drop ``None`` object keys to match JSON.stringify's undefined omission."""
    if isinstance(value, dict):
        return {
            key: _strip_undefined(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_strip_undefined(item) for item in value]
    return value


def serialize_action_descriptions(
    action_descriptions: list[Any], action_space_format: str = "yaml"
) -> str:
    if action_space_format == "jsonl":
        import json as _json

        return "\n".join(
            _json.dumps(
                _strip_undefined(description),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for description in action_descriptions
        )
    return yaml.dump(
        action_descriptions,
        Dumper=_LiteralBlockDumper,
        indent=2,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10**6,
    ).strip()


def build_planning_action_space_description(
    action_space: Sequence[Any],
    planning_protocol: StandardPlanningProtocol,
    locate_prompt_spec: dict[str, Any] | None = None,
) -> str:
    locate_field_description = planning_protocol["action_space_protocol"][
        "build_locate_field_description"
    ](locate_prompt_spec)

    action_output_protocol = planning_protocol["action_output_protocol"]
    include_example = planning_protocol["action_space_protocol"][
        "include_action_output_example"
    ]

    descriptions = []
    for action in action_space:
        action_output_example = (
            build_action_output_example(
                action if isinstance(action, dict) else action.to_prompt_dict(),
                action_output_protocol["build_action_output"],
                locate_prompt_spec,
            )
            if include_example
            else None
        )
        descriptions.append(
            planning_protocol["action_space_protocol"]["build_action_description"](
                {
                    "action": action,
                    "locate_field_description": locate_field_description,
                    "action_output_example": action_output_example,
                }
            )
        )

    action_space_format = planning_protocol["action_space_protocol"].get(
        "format", "yaml"
    )
    return serialize_action_descriptions(descriptions, action_space_format)


def build_locate_field_description(
    locate_prompt_spec: dict[str, Any] | None = None,
) -> str:
    if locate_prompt_spec:
        return (
            "{ prompt: string, "
            f"{locate_prompt_spec['resultKey']}: {locate_prompt_spec['resultValueSchema']}"
            f" /* {locate_prompt_spec['resultValueDescription']} */ }}"
        )
    return "{ prompt: string /* description of the target element */ }"


__all__ = [
    "build_locate_field_description",
    "build_planning_action_space_description",
    "serialize_action_descriptions",
]
