"""Action output examples (upstream prompt/planning/action-output-example.ts)."""

from typing import Any


def _inject_locate_result_into_sample(
    sample: dict[str, Any],
    locate_fields: list[str],
    prompt_spec: dict[str, Any],
    locate_result_example_index: int,
) -> dict[str, Any]:
    result = dict(sample)
    example_index = locate_result_example_index
    for field in locate_fields:
        value = result.get(field)
        if isinstance(value, dict) and value.get("prompt"):
            example_values = prompt_spec["exampleValues"]
            result[field] = {
                **value,
                prompt_spec["resultKey"]: example_values[
                    example_index % len(example_values)
                ],
            }
            example_index += 1
    return result


def build_action_output_example(
    action: dict[str, Any],
    build_action_output,
    locate_prompt_spec: dict[str, Any] | None = None,
    locate_result_example_index: int = 0,
) -> str | None:
    sample = action.get("sample")
    if not isinstance(sample, dict):
        return None

    locate_fields = list(action.get("locate_fields", []))
    sample_with_locate_result = (
        _inject_locate_result_into_sample(
            sample, locate_fields, locate_prompt_spec, locate_result_example_index
        )
        if locate_prompt_spec
        else sample
    )

    return build_action_output(
        {
            "actionName": action["name"],
            "param": sample_with_locate_result,
            "locateFields": locate_fields,
            "locateResultKey": locate_prompt_spec.get("resultKey")
            if locate_prompt_spec
            else None,
        }
    )


def create_sample_tap_action(prompt: str) -> dict[str, Any]:
    return {
        "name": "Tap",
        "sample": {"locate": {"prompt": prompt}},
        "locate_fields": ["locate"],
    }


def create_sample_input_action(value: str) -> dict[str, Any]:
    return {"name": "Input", "sample": {"value": value}, "locate_fields": ["locate"]}


__all__ = [
    "build_action_output_example",
    "create_sample_input_action",
    "create_sample_tap_action",
]
