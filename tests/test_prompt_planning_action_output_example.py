"""Synced from upstream packages/core/tests/unit-test/prompt/planning/action-output-example.test.ts."""

from midscene.core.ai_model.model_adapter.default_planning_protocol import (
    build_planning_action_output,
    create_default_planning_protocol,
)
from midscene.core.ai_model.prompt.planning.action_output_example import (
    build_action_output_example,
    create_sample_tap_action,
)


def test_serializes_an_action_type_and_structured_parameters():
    """serializes an action type and structured parameters"""
    assert build_planning_action_output(
        {
            "actionName": "Input",
            "param": {"value": "john@example.com"},
        }
    ) == (
        "<action-type>Input</action-type>\n"
        "<action-param-json>\n"
        "{\n"
        '  "value": "john@example.com"\n'
        "}\n"
        "</action-param-json>"
    )


def test_serializes_nested_locator_parameters():
    """serializes nested locator parameters"""
    assert build_planning_action_output(
        {
            "actionName": "Tap",
            "param": {
                "locate": {
                    "prompt": "the Submit button",
                    "bbox": [100, 200, 300, 400],
                }
            },
        }
    ) == (
        "<action-type>Tap</action-type>\n"
        "<action-param-json>\n"
        "{\n"
        '  "locate": {\n'
        '    "prompt": "the Submit button",\n'
        '    "bbox": [\n'
        "      100,\n"
        "      200,\n"
        "      300,\n"
        "      400\n"
        "    ]\n"
        "  }\n"
        "}\n"
        "</action-param-json>"
    )


def test_builds_an_action_output_protocol_example():
    """builds an action output protocol example"""
    action_output_protocol = create_default_planning_protocol()[
        "action_output_protocol"
    ]
    build_action_output = action_output_protocol["build_action_output"]

    action_output_example = build_action_output_example(
        {
            "name": "Tap",
            "sample": {"locate": {"prompt": "the Submit button"}},
        },
        build_action_output=build_action_output,
    )

    assert action_output_example == (
        "<action-type>Tap</action-type>\n"
        "<action-param-json>\n"
        "{\n"
        '  "locate": {\n'
        '    "prompt": "the Submit button"\n'
        "  }\n"
        "}\n"
        "</action-param-json>"
    )


def test_injects_a_locate_result_starting_from_the_requested_example_index():
    """injects a locate result starting from the requested example index"""
    locate_prompt_spec = {
        "resultKey": "bbox",
        "resultValueSchema": "[number, number, number, number]",
        "resultValueDescription": "bounding box coordinates",
        "resultNoun": "bounding box",
        "resultNounPlural": "bounding boxes",
        "exampleValues": [
            [100, 100, 200, 200],
            [345, 442, 458, 483],
            [120, 180, 380, 210],
        ],
    }

    action_output_example = build_action_output_example(
        create_sample_tap_action("Name input field"),
        build_action_output=build_planning_action_output,
        locate_prompt_spec=locate_prompt_spec,
        locate_result_example_index=2,
    )

    assert '"bbox": [120, 180, 380, 210]' in action_output_example


def test_keeps_non_locate_arrays_in_standard_pretty_json_format():
    """keeps non-locate arrays in standard pretty JSON format"""
    action_output_example = build_action_output_example(
        {
            "name": "TapWithOffsets",
            "sample": {
                "locate": {"prompt": "Name input field"},
                "offsets": [10, 20],
            },
            "locate_fields": ["locate"],
        },
        build_action_output=build_planning_action_output,
        locate_prompt_spec={
            "resultKey": "bbox",
            "resultValueSchema": "[number, number, number, number]",
            "resultValueDescription": "bounding box coordinates",
            "resultNoun": "bounding box",
            "resultNounPlural": "bounding boxes",
            "exampleValues": [[100, 100, 200, 200]],
        },
    )

    assert '"bbox": [100, 100, 200, 200]' in action_output_example
    assert '"offsets": [\n    10,\n    20\n  ]' in action_output_example
