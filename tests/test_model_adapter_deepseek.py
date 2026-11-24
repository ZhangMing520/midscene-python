"""Synced from upstream packages/core/tests/unit-test/model-adapter/deepseek.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.models.deepseek.adapter import deep_seek_adapters
from midscene.core.ai_model.models.deepseek.locate_protocol import (
    deep_seek_element_locate_protocol,
    deep_seek_search_area_protocol,
    parse_deep_seek_locate_output,
    parse_deep_seek_search_area_output,
)
from midscene.core.ai_model.models.registry import get_model_adapter
from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_prompt_spec,
    resolve_locate_result_coordinates,
)


def _deepseek_locate():
    locate = resolve_locate(get_model_adapter("deepseek"))
    assert locate["kind"] == "standard"
    return locate


@pytest.mark.parametrize(
    "base_url,open_router",
    [
        ("https://api.deepseek.com", False),
        ("https://openrouter.ai/api/v1", True),
    ],
    ids=["native", "openrouter"],
)
@pytest.mark.parametrize(
    "reasoning_enabled,native,router,temperature",
    [
        (
            None,
            {"thinking": {"type": "disabled"}},
            {"reasoning": {"enabled": False}},
            0.7,
        ),
        (
            False,
            {"thinking": {"type": "disabled"}},
            {"reasoning": {"enabled": False}},
            0.7,
        ),
        (
            True,
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
            {"reasoning": {"enabled": True, "effort": "max", "max_tokens": 1024}},
            None,
        ),
        ("default", {}, {}, None),
    ],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_reasoning_with_endpoint_specific_effort_and_budget(
    base_url, open_router, reasoning_enabled, native, router, temperature
):
    """maps enabled with endpoint-specific effort and budget"""
    result = deep_seek_adapters["deepseek"]["chat_completion"][
        "build_chat_completion_params"
    ](
        {
            "baseURL": base_url,
            "expectedJsonObjectResponse": True,
            "userConfig": {
                "reasoningEnabled": reasoning_enabled,
                "reasoningEffort": "max",
                "reasoningBudget": 1024,
                "temperature": 0.7,
            },
        }
    )
    config = {
        key: value for key, value in result["config"].items() if value is not None
    }
    expected = {
        "response_format": {"type": "json_object"},
        **(router if open_router else native),
    }
    if temperature is not None:
        expected["temperature"] = temperature
    assert config == expected


def test_omits_empty_reasoning_configuration_for_default_without_effort():
    """omits empty reasoning configuration for default without effort"""
    result = deep_seek_adapters["deepseek"]["chat_completion"][
        "build_chat_completion_params"
    ]({"userConfig": {"reasoningEnabled": "default"}})
    assert {
        key: value for key, value in result["config"].items() if value is not None
    } == {}


def test_uses_point_tokens_for_final_element_locate():
    """uses point tokens for final element locate"""
    element = _deepseek_locate()["element"]
    protocol = element["protocol"]
    response_instructions = protocol["build_response_instructions"](
        element["result_codec"].prompt_spec
    )
    assert (
        "You are a GUI click grounding agent." in protocol["system_prompt_introduction"]
    )
    assert "<｜｜point｜｜>[[number, number]]<｜｜/point｜｜>" in response_instructions
    assert "<｜｜point｜｜>[[150, 150]]<｜｜/point｜｜>" in response_instructions
    assert (
        "Coordinate requirements: point, should be [x, y] normalized to 0-1000 "
        "relative to the screenshot." in response_instructions
    )
    assert protocol["expected_json_object_response"] is False
    assert (
        protocol["build_user_prompt"]("Submit")
        == "Locate the center point of the following UI element: Submit"
    )


def test_builds_coordinate_instructions_from_the_result_format_prompt_spec():
    """builds coordinate instructions from the result format prompt spec"""
    point_spec = create_locate_result_prompt_spec(
        resolve_locate_result_coordinates(
            {"shape": "point", "order": "yx", "normalizedBy": 2000, "rounding": "round"}
        )
    )
    bbox_spec = create_locate_result_prompt_spec(
        resolve_locate_result_coordinates(
            {"shape": "bbox", "order": "yx", "normalizedBy": 2000, "rounding": "round"}
        )
    )
    element_instructions = deep_seek_element_locate_protocol[
        "build_response_instructions"
    ](point_spec)
    search_area_instructions = deep_seek_search_area_protocol[
        "build_response_instructions"
    ](bbox_spec)
    assert "should be [y, x]" in element_instructions
    assert "normalized to 0-2000" in element_instructions
    assert "normalized to 0-1000" not in element_instructions
    assert "should be [ymin, xmin, ymax, xmax]" in search_area_instructions
    assert "normalized to 0-2000" in search_area_instructions
    assert "normalized to 0-1000" not in search_area_instructions


def test_parses_a_normalized_final_point_and_maps_it_to_pixels():
    """parses a normalized final point and maps it to pixels"""
    element = _deepseek_locate()["element"]
    raw_result = element["protocol"]["parse_raw_response"](
        "<｜｜point｜｜>[[928,780]]<｜｜/point｜｜>",
        element["result_codec"].prompt_spec,
    )
    assert raw_result == {"kind": "located", "target": "[[928,780]]"}
    assert element["result_codec"].to_pixel_result(
        raw_result["target"], {"preparedSize": {"width": 1000, "height": 1000}}
    ) == {"center": (928, 780), "rect": None}


def test_uses_ref_box_tokens_and_bbox_coordinates_for_search_area():
    """uses ref-box tokens and bbox coordinates for deepLocate search area"""
    locate = _deepseek_locate()
    search_area = locate["search_area"]
    response_instructions = search_area["protocol"]["build_response_instructions"](
        search_area["result_codec"].prompt_spec
    )
    assert (
        "You are a GUI grounding agent."
        in search_area["protocol"]["system_prompt_introduction"]
    )
    assert (
        "you MUST return that visible element as a reference" in response_instructions
    )
    assert (
        "<｜｜ref｜｜>target: concise target description<｜｜/ref｜｜>"
        "<｜｜box｜｜>[[number, number, number, number]]<｜｜/box｜｜>"
        in response_instructions
    )
    assert (
        "Coordinate requirements: 2d bounding box, should be "
        "[xmin, ymin, xmax, ymax] normalized to 0-1000 relative to the screenshot."
        in response_instructions
    )
    assert (
        search_area["protocol"]["build_user_prompt"]("the Apollo edit icon")
        == "Locate the target and the reference elements needed to distinguish it: "
        "the Apollo edit icon"
    )
    assert search_area["protocol"]["expected_json_object_response"] is False
    raw_result = search_area["protocol"]["parse_raw_response"](
        "<｜｜ref｜｜>target: edit icon<｜｜/ref｜｜>"
        "<｜｜box｜｜>[[845,390,875,430]]<｜｜/box｜｜>\n"
        "<｜｜ref｜｜>reference: Apollo<｜｜/ref｜｜>"
        "<｜｜box｜｜>[[150,390,230,430]]<｜｜/box｜｜>",
        search_area["result_codec"].prompt_spec,
    )
    assert raw_result == {
        "kind": "located",
        "target": "[[845,390,875,430]]",
        "references": ["[[150,390,230,430]]"],
    }
    context = {"preparedSize": {"width": 1000, "height": 1000}}
    assert search_area["result_codec"].to_pixel_result(raw_result["target"], context)[
        "rect"
    ] == {"left": 845, "top": 390, "width": 31, "height": 41}
    assert [
        search_area["result_codec"].to_pixel_result(reference, context)["rect"]
        for reference in raw_result["references"]
    ] == [{"left": 150, "top": 390, "width": 81, "height": 41}]


def test_accepts_ascii_ref_box_delimiters_when_no_reference_is_needed():
    """accepts ASCII ref-box delimiters when no reference is needed"""
    assert parse_deep_seek_search_area_output(
        "<|ref|>target: Submit button<|/ref|><|box|>[[300,440,360,480]]<|/box|>"
    ) == {"kind": "located", "target": "[[300,440,360,480]]"}


def test_rejects_responses_that_do_not_contain_exactly_two_integers():
    """rejects responses that do not contain exactly two integers"""
    element = _deepseek_locate()["element"]
    raw_result = element["protocol"]["parse_raw_response"](
        "<｜｜point｜｜>[[820,430],[210,430]]<｜｜/point｜｜>",
        element["result_codec"].prompt_spec,
    )
    with pytest.raises(ValueError, match="must contain exactly 2 positive integers"):
        element["result_codec"].to_pixel_result(
            raw_result["target"], {"preparedSize": {"width": 1000, "height": 1000}}
        )


@pytest.mark.parametrize(
    "content",
    [
        "[[928,780]]",
        "<｜｜point｜｜>[[928,780]]<｜｜/point｜｜>extra text",
    ],
    ids=["no-envelope", "trailing-text"],
)
def test_rejects_responses_without_exactly_one_point_envelope(content):
    """rejects responses without exactly one point envelope"""
    with pytest.raises(ValueError, match="does not contain a valid"):
        parse_deep_seek_locate_output(content)


@pytest.mark.parametrize(
    "content",
    [
        "<｜｜point｜｜>[[928.5,780]]<｜｜/point｜｜>",
        "<｜｜point｜｜>no coordinates<｜｜/point｜｜>",
    ],
    ids=["float", "no-coordinates"],
)
def test_rejects_output_without_exactly_two_integers(content):
    """rejects output without exactly two integers"""
    element = _deepseek_locate()["element"]
    raw_result = element["protocol"]["parse_raw_response"](
        content, element["result_codec"].prompt_spec
    )
    with pytest.raises(ValueError, match="must contain exactly 2 positive integers"):
        element["result_codec"].to_pixel_result(
            raw_result["target"], {"preparedSize": {"width": 1000, "height": 1000}}
        )


@pytest.mark.parametrize(
    "content",
    [
        "<｜｜point｜｜>[928,780]<｜｜/point｜｜>",
        "<｜｜point｜｜>[[928 780]]<｜｜/point｜｜>",
        "<|point|>928 -> 780<|/point|>",
    ],
    ids=["array", "space", "arrows"],
)
def test_accepts_any_separator_between_the_two_integers(content):
    """accepts any separator between the two integers"""
    element = _deepseek_locate()["element"]
    raw_result = element["protocol"]["parse_raw_response"](
        content, element["result_codec"].prompt_spec
    )
    assert element["result_codec"].to_pixel_result(
        raw_result["target"], {"preparedSize": {"width": 1000, "height": 1000}}
    ) == {"center": (928, 780), "rect": None}


def test_maps_deepseek_reasoning_controls_and_provider_defaults():
    """maps DeepSeek reasoning controls and provider defaults"""
    builder = deep_seek_adapters["deepseek"]["chat_completion"][
        "build_chat_completion_params"
    ]

    def build(user_config):
        return {
            key: value
            for key, value in builder({"userConfig": user_config})["config"].items()
            if value is not None
        }

    assert build({}) == {"temperature": 0, "thinking": {"type": "disabled"}}
    assert build({"reasoningEnabled": True, "reasoningEffort": "max"}) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }
    assert (
        build(
            {
                "reasoningEnabled": "default",
                "reasoningEffort": "max",
                "temperature": 0.7,
            }
        )
        == {}
    )
    assert build({"reasoningEnabled": False, "temperature": 0.7}) == {
        "temperature": 0.7,
        "thinking": {"type": "disabled"},
    }


def test_does_not_replay_raw_assistant_messages_without_tool_calls():
    """does not replay raw assistant messages without tool calls"""
    chat_completion = deep_seek_adapters["deepseek"]["chat_completion"]
    assert chat_completion["use_reasoning_as_content_fallback"] is True
    assert chat_completion["replay_raw_assistant_message"] is False
