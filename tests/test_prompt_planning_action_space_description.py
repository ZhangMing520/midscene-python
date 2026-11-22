"""Synced from upstream packages/core/tests/unit-test/prompt/planning/action-space-description.test.ts."""

from midscene.core.ai_model.prompt.planning.action_space_description import (
    build_planning_action_space_description,
)


def _planning_protocol(
    include_action_output_example,
    build_locate_field_description,
    build_action_description,
    build_action_output,
):
    return {
        "action_space_protocol": {
            "title": "Functions",
            "format": "jsonl",
            "include_action_output_example": include_action_output_example,
            "build_locate_field_description": build_locate_field_description,
            "build_action_description": build_action_description,
        },
        "action_output_protocol": {
            "action_output_tag_names": ["tool"],
            "action_output_rules": "Return a tool.",
            "action_output_placeholder": "<tool>...</tool>",
            "build_action_output": build_action_output,
            "parse_action_output": lambda content, action_space: None,
            "parse_raw_locate_parameter": lambda value: value,
        },
    }


def test_builds_examples_and_serializes_protocol_specific_action_descriptions():
    """builds examples and serializes protocol-specific action descriptions"""
    locate_prompt_spec = {
        "resultKey": "point",
        "resultValueSchema": "[number, number]",
        "resultValueDescription": "point coordinates",
        "resultNoun": "point",
        "resultNounPlural": "points",
        "exampleValues": [[500, 500]],
    }
    calls = {"locate_field_description": [], "build_action_output": []}

    def build_locate_field_description(spec):
        calls["locate_field_description"].append(spec)
        return "LOCATE_FIELD"

    def build_action_output(build_input):
        calls["build_action_output"].append(build_input)
        return f"<tool>{build_input['actionName']}</tool>"

    def build_action_description(build_input):
        return {
            "name": build_input["action"]["name"],
            "locateFieldDescription": build_input["locate_field_description"],
            "actionOutputExample": build_input["action_output_example"],
        }

    planning_protocol = _planning_protocol(
        True,
        build_locate_field_description,
        build_action_description,
        build_action_output,
    )

    result = build_planning_action_space_description(
        action_space=[
            {
                "name": "Tap",
                "description": "Tap an element",
                "sample": {"locate": {"prompt": "the Submit button"}},
                "locate_fields": ["locate"],
            }
        ],
        planning_protocol=planning_protocol,
        locate_prompt_spec=locate_prompt_spec,
    )

    assert result == (
        '{"name":"Tap","locateFieldDescription":"LOCATE_FIELD",'
        '"actionOutputExample":"<tool>Tap</tool>"}'
    )
    assert calls["locate_field_description"] == [locate_prompt_spec]
    assert calls["build_action_output"] == [
        {
            "actionName": "Tap",
            "param": {
                "locate": {
                    "prompt": "the Submit button",
                    "point": [500, 500],
                }
            },
            "locateFields": ["locate"],
            "locateResultKey": "point",
        }
    ]


def test_skips_action_output_examples_when_the_action_space_protocol_excludes_them():
    """skips action output examples when the action space protocol excludes them"""
    calls = {"build_action_output": []}

    def build_action_output(build_input):
        calls["build_action_output"].append(build_input)
        return "<tool>Tap</tool>"

    def build_action_description(build_input):
        return {
            "name": build_input["action"]["name"],
            "actionOutputExample": build_input["action_output_example"],
        }

    planning_protocol = _planning_protocol(
        False,
        lambda spec: "LOCATE_FIELD",
        build_action_description,
        build_action_output,
    )

    assert build_planning_action_space_description(
        action_space=[
            {
                "name": "Tap",
                "sample": {"locate": {"prompt": "the Submit button"}},
                "locate_fields": ["locate"],
            }
        ],
        planning_protocol=planning_protocol,
    ) == '{"name":"Tap"}'
    assert calls["build_action_output"] == []
