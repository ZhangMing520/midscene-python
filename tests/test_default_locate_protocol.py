"""Synced from upstream packages/core/tests/unit-test/model-adapter/default-locate-protocol.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.default_locate_protocol import (
    create_default_element_protocol,
)
from midscene.core.ai_model.prompt.locate import build_element_locate_system_prompt


def test_parses_the_existing_json_locate_response():
    protocol = create_default_element_protocol()
    prompt_spec = {
        "resultKey": "bbox",
        "resultKeyAliases": [],
        "exampleValues": [[1, 2, 3, 4]],
    }

    parsed = protocol["parse_raw_response"](
        '```json\n{"bbox": [10, 10, 20, 20]}\n```', prompt_spec
    )
    assert parsed["kind"] == "located"
    assert parsed["target"] == [10, 10, 20, 20]

    not_found = protocol["parse_raw_response"](
        '{"bbox": [], "error": "not found"}', prompt_spec
    )
    assert not_found["kind"] == "not-found"
    assert not_found["error"] == "not found"


def test_rejects_a_response_missing_the_required_coordinate_field():
    protocol = create_default_element_protocol()
    prompt_spec = {"resultKey": "bbox", "resultKeyAliases": []}

    with pytest.raises(ValueError) as exc:
        protocol["parse_raw_response"]('{"wrong": [1,2,3,4]}', prompt_spec)

    assert "Missing required coordinate field" in str(exc.value)


def test_builds_the_existing_json_locate_prompts():
    prompt = build_element_locate_system_prompt("Intro", "Output")

    assert "Important Notes for Locating Elements" in prompt
    assert "Intro" in prompt and "Output" in prompt
