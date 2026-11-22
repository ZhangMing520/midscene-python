"""Synced from upstream packages/core/tests/unit-test/json.test.ts."""

import pytest

from midscene.core.ai_model.shared.json import (
    assert_json_object,
    parse_model_response_json,
)


def test_should_extract_json_from_a_code_block_with_json_language_specifier():
    raw = '```json\n{"bbox": [1, 2, 3, 4]}\n```'
    assert parse_model_response_json(raw) == {"bbox": [1, 2, 3, 4]}


def test_should_parse_dirty_json_that_jsonrepair_can_fix():
    raw = '{"bbox": [1, 2, 3, 4], "prompt": "the button",}'
    assert parse_model_response_json(raw)["bbox"] == [1, 2, 3, 4]


def test_should_trim_leading_and_trailing_spaces_from_type_field_values():
    parsed = parse_model_response_json('{"type": " Tap "}')
    assert parsed["type"] == "Tap"


def test_should_preserve_configured_string_value_keys_while_trimming_other_fields():
    parsed = parse_model_response_json(
        '{"value": " spaced ", "type": " Tap "}',
        preserve_string_value_keys=["value"],
    )
    assert parsed["value"] == " spaced "
    assert parsed["type"] == "Tap"


def test_should_reject_non_object_json_values():
    with pytest.raises(ValueError):
        assert_json_object([1, 2])


def test_should_preserve_arrays_when_repairing_malformed_json():
    raw = '[{"index": 1}, {"index": 2}]'
    assert parse_model_response_json(raw) == [{"index": 1}, {"index": 2}]


def test_should_preserve_arrays_from_a_json_code_block():
    raw = '```json\n[{"name": "a"}, {"name": "b"}]\n```'
    assert parse_model_response_json(raw) == [{"name": "a"}, {"name": "b"}]


def test_should_repair_array_trailing_commas():
    raw = '[{"index": 1}, {"index": 2},]'
    assert parse_model_response_json(raw) == [{"index": 1}, {"index": 2}]


def test_should_ignore_non_json_code_blocks_before_the_payload():
    raw = 'Here is the script:\n```python\nprint(1)\n```\n{"bbox": [1, 2]}'
    assert parse_model_response_json(raw) == {"bbox": [1, 2]}


def test_should_extract_json_like_structure_from_text():
    raw = 'Here is the result: {"bbox": [1, 2, 3, 4]} hope it helps'
    assert parse_model_response_json(raw) == {"bbox": [1, 2, 3, 4]}
