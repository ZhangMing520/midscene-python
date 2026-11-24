"""Synced from upstream packages/core/tests/unit-test/model-adapter/doubao.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.models.doubao import (
    _build_doubao_params,
    _parse_doubao_raw_locate_value,
)
from midscene.core.ai_model.models.registry import get_model_adapter
from midscene.core.ai_model.shared.json import parse_model_response_json
from midscene.core.ai_model.shared.model_locate_result import (
    resolve_locate_result_coordinates,
)

FAMILIES = ["doubao-seed", "doubao-vision"]


def _build(
    family, base_url=None, user_config=None, expected=False, midscene_defaults=None
):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_doubao_params(
        {"temperature": 0.0} if midscene_defaults is None else midscene_defaults,
        user,
        expected,
    )


def _vision_locate_codec():
    locate = resolve_locate(get_model_adapter("doubao-vision"))
    assert locate["kind"] == "standard"
    return locate["element"]["result_codec"]


def _resolved(value):
    """Resolve parser metadata defaults the way the codec does."""
    return {
        "coordinates": value["coordinates"],
        "coordinatesMeta": resolve_locate_result_coordinates(value["coordinatesMeta"]),
    }


def _bbox_meta():
    return {
        "normalizationBasis": "image-size",
        "boundsType": "closed",
        "shape": "bbox",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    }


def _point_meta():
    return {
        "normalizationBasis": "image-size",
        "shape": "point",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    }


def _shared_parser(raw, source, preserve_string_value_keys=None):
    return parse_model_response_json(
        raw,
        source=source,
        preserve_string_value_keys=preserve_string_value_keys,
    )


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "reasoning_enabled,native,open_router",
    [
        (
            None,
            {"thinking": {"type": "disabled"}},
            {"reasoning": {"enabled": False}},
        ),
        (
            False,
            {"thinking": {"type": "disabled"}},
            {"reasoning": {"enabled": False}},
        ),
        (
            True,
            {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
            {"reasoning": {"enabled": True, "effort": "high", "max_tokens": 1024}},
        ),
        ("default", {}, {}),
    ],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_enabled_for_both_endpoints(
    family, reasoning_enabled, native, open_router
):
    """maps enabled=$reasoningEnabled for both endpoints"""
    user_config = {
        "reasoningEnabled": reasoning_enabled,
        "reasoningEffort": "high",
        "reasoningBudget": 1024,
        "temperature": 0.7,
    }
    for base_url, expected in [
        ("https://ark.cn-beijing.volces.com/api/v3", native),
        ("https://openrouter.ai/api/v1", open_router),
    ]:
        result = _build(family, base_url, user_config, True)
        assert result == {
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
            **expected,
        }


@pytest.mark.parametrize("family", FAMILIES)
def test_omits_reasoning_configuration_when_using_default_without_effort(family):
    """omits reasoning configuration when using default without effort"""
    for base_url in [None, "https://openrouter.ai/api/v1"]:
        result = _build(family, base_url, {"reasoningEnabled": "default"})
        assert result == {"temperature": 0}


def test_keeps_doubao_seed_and_doubao_vision_json_parsing_behavior_aligned():
    """keeps doubao-seed and doubao-vision json parsing behavior aligned"""
    seed = get_model_adapter("doubao-seed")
    vision = get_model_adapter("doubao-vision")
    # An unset adapter parser resolves to the shared JSON parser.
    assert (seed.json_parser or parse_model_response_json) is (
        vision.json_parser or parse_model_response_json
    )


def test_defaults_doubao_thinking_to_disabled_when_reasoning_config_is_unset():
    """defaults doubao thinking to disabled when reasoning config is unset"""
    result = _build("doubao-seed")
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_uses_json_object_response_format_when_expected_unless_disabled():
    """uses json_object response format when expected unless disabled"""
    auto_result = _build("doubao-vision", expected=True)
    disabled_result = _build(
        "doubao-vision", user_config={"responseFormat": "none"}, expected=True
    )

    assert auto_result["response_format"] == {"type": "json_object"}
    assert "response_format" not in disabled_result


def test_preserves_midscene_defaults_and_applies_explicit_doubao_temperature_override():
    """preserves midscene defaults and applies explicit doubao temperature override"""
    result = _build(
        "doubao-seed",
        user_config={"temperature": 0.7, "reasoningEnabled": True},
        midscene_defaults={"temperature": 0, "seed": 123},
    )

    assert result == {
        "temperature": 0.7,
        "seed": 123,
        "thinking": {"type": "enabled"},
    }


def test_omits_maxtokens_from_adapter_owned_chat_completion_params():
    """omits maxTokens from adapter-owned chat completion params"""
    result = _build("doubao-seed", user_config={"maxTokens": 2048})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_maps_reasoningenabled_to_thinking_type_for_doubao_vision():
    """maps reasoningEnabled to thinking.type for doubao-vision"""
    result = _build("doubao-vision", user_config={"reasoningEnabled": True})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "enabled"},
    }


def test_maps_reasoningenabled_false_to_thinking_type_disabled_for_doubao_seed():
    """maps reasoningEnabled=false to thinking.type=disabled for doubao-seed"""
    result = _build("doubao-seed", user_config={"reasoningEnabled": False})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_maps_reasoningenabled_with_reasoningeffort_for_doubao_vision():
    """maps reasoningEnabled with reasoningEffort for doubao-vision"""
    result = _build(
        "doubao-vision",
        user_config={"reasoningEnabled": True, "reasoningEffort": "medium"},
    )
    assert result == {
        "temperature": 0,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "medium",
    }


def test_maps_both_reasoningenabled_and_reasoningeffort_for_doubao_seed():
    """maps both reasoningEnabled and reasoningEffort for doubao-seed"""
    result = _build(
        "doubao-seed",
        user_config={"reasoningEnabled": True, "reasoningEffort": "high"},
    )
    assert result == {
        "temperature": 0,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def test_follows_provider_default_and_ignores_effort_for_doubao_when_reasoningenabled_default():
    """follows provider default and ignores effort for doubao when reasoningEnabled=default"""
    result = _build(
        "doubao-seed",
        user_config={"reasoningEnabled": "default", "reasoningEffort": "high"},
    )
    assert result == {"temperature": 0}


def test_ignores_reasoningbudget_for_doubao():
    """ignores reasoningBudget for doubao"""
    result = _build("doubao-seed", user_config={"reasoningBudget": 1024})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_parses_locate_like_json_through_the_shared_parser():
    """parses locate-like JSON through the shared parser"""
    parse = lambda raw: _shared_parser(raw, "locate")  # noqa: E731

    assert parse('{"bbox": [123 456]}') == {"bbox": [123, 456]}
    assert parse('{"bbox": [1 4]}') == {"bbox": [1, 4]}
    assert parse('{"bbox": [123 456,789 100]}') == {"bbox": [123, 456, 789, 100]}
    assert parse('{"bbox": [940 445 969 490]}') == {"bbox": [940, 445, 969, 490]}
    with pytest.raises(ValueError):
        parse("123 345 11111")

    input_text = """
{
  "bbox": [
    "550 216",
    "550 216",
    "550 216",
    "550 216"
  ]
}
    """
    assert parse(input_text) == {"bbox": ["550 216", "550 216", "550 216", "550 216"]}


def test_does_not_repair_malformed_json_for_generic_parser_sources():
    """does not repair malformed json for generic parser sources"""
    with pytest.raises(ValueError):
        _shared_parser("```", "generic-object")


def test_normalizes_parsed_doubao_json_while_preserving_configured_string_values():
    """normalizes parsed doubao json while preserving configured string values"""
    result = _shared_parser(
        '{" value ": "  keep spaces  ", " bbox ": [" 123 456 "]}',
        "locate",
        preserve_string_value_keys=["value"],
    )

    assert result == {
        "value": "  keep spaces  ",
        "bbox": ["123 456"],
    }


def test_repairs_planning_action_params_with_bbox_coordinates():
    """repairs planning action params with bbox coordinates"""
    result = _shared_parser(
        '{"locate": {"bbox": [123 456 789 100]}}', "planning-action-param"
    )
    assert result == {
        "locate": {"bbox": [123, 456, 789, 100]},
    }


def test_normalizes_doubao_bbox_coordinates():
    """normalizes doubao bbox coordinates"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200, 300, 400],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 100,
        "top": 400,
        "width": 201,
        "height": 401,
    }


def test_normalizes_doubao_space_separated_bbox_string_coordinates():
    """normalizes doubao space-separated bbox string coordinates"""
    codec = _vision_locate_codec()
    size = {"preparedSize": {"width": 1000, "height": 2000}}

    assert codec.to_pixel_result("100 200 300 400", size)["rect"] == {
        "left": 100,
        "top": 400,
        "width": 201,
        "height": 401,
    }
    assert codec.to_pixel_result("[336, 163, 717, 200]", size)["rect"] == {
        "left": 336,
        "top": 326,
        "width": 382,
        "height": 75,
    }


def test_parses_valid_raw_doubao_locate_values_directly():
    """parses valid raw Doubao locate values directly"""
    assert _resolved(_parse_doubao_raw_locate_value([100, 200, 300, 400])) == {
        "coordinates": [100, 200, 300, 400],
        "coordinatesMeta": _bbox_meta(),
    }


@pytest.mark.parametrize(
    "input_value,expected_coordinates,expected_meta",
    [
        ("100 200 300 400", [100, 200, 300, 400], _bbox_meta()),
        (["100", "200", "300", "400"], [100, 200, 300, 400], _bbox_meta()),
        ("100 200 300 400 ", [100, 200, 300, 400], _bbox_meta()),
        ("[336, 163, 717, 200]", [336, 163, 717, 200], _bbox_meta()),
        ("336,163,717,200", [336, 163, 717, 200], _bbox_meta()),
        ([653, "277; 664 291;"], [653, 277, 664, 291], _bbox_meta()),
        ([653, "277, 664, 291,"], [653, 277, 664, 291], _bbox_meta()),
        (["bbox", [782, 541, 815, 559]], [782, 541, 815, 559], _bbox_meta()),
        (["bbox", "782, 541, 815, 559"], [782, 541, 815, 559], _bbox_meta()),
        (
            [410, 295, 885, "345<", '/bbox>,\n  "error": ""\n}'],
            [410, 295, 885, 345],
            _bbox_meta(),
        ),
        (["bbox_859_773_923_808"], [859, 773, 923, 808], _bbox_meta()),
        ("bbox_859_773_923_808", [859, 773, 923, 808], _bbox_meta()),
        (["bbox_2d", [650, 700, 710, 730]], [650, 700, 710, 730], _bbox_meta()),
        (["-100", 200, 300, 400], [100, 200, 300, 400], _bbox_meta()),
        (["100.5", 200, 300, 400], [100, 5, 200, 300], _bbox_meta()),
        (
            "error: 500, 503; bbox_100_200_300_400",
            [100, 200, 300, 400],
            _bbox_meta(),
        ),
        (
            [[100, 200, 300, 400], [500, 600, 700, 800]],
            [100, 200, 300, 400],
            _bbox_meta(),
        ),
        ("100 200 300", [100, 200], _point_meta()),
        ("1 2 3 4 5 6 7 8", [1, 2, 5, 6], _bbox_meta()),
    ],
    ids=[
        "space-separated string",
        "separate numeric strings",
        "trailing whitespace",
        "bracketed coordinate string",
        "comma-separated string",
        "mixed numbers and semicolon-delimited string",
        "mixed numbers and trailing comma-delimited string",
        "bbox tag wrapping coordinates",
        "bbox tag wrapping a coordinate string",
        "JSON repair output with an XML-style closing tag",
        "underscore-delimited bbox token from JSON repair",
        "underscore-delimited bbox string",
        "coordinates following bbox_2d metadata",
        "negative sign ignored in malformed coordinate structure",
        "decimal coordinate split into integer tokens",
        "longer coordinate sequence over shorter error-code sequence",
        "first bbox from a nested bbox list",
        "three-number string point fallback",
        "eight-number polygon string",
    ],
)
def test_parses_malformed_raw_doubao_locate_value(
    input_value, expected_coordinates, expected_meta
):
    """parses malformed raw Doubao locate value: $name"""
    assert _resolved(_parse_doubao_raw_locate_value(input_value)) == {
        "coordinates": expected_coordinates,
        "coordinatesMeta": expected_meta,
    }


@pytest.mark.parametrize(
    "input_value",
    [
        "100",
        "first: 100 200 300 400; second: 500 600 700 800",
    ],
    ids=[
        "without a coordinate sequence",
        "with two equal-length coordinate sequences",
    ],
)
def test_throws_on_raw_doubao_locate_values(input_value):
    """throws on raw Doubao locate values %s"""
    with pytest.raises(ValueError, match="invalid bbox data"):
        _parse_doubao_raw_locate_value(input_value)


def test_normalizes_doubao_five_number_bbox_by_using_the_first_four_values():
    """normalizes doubao five-number bbox by using the first four values"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200, 300, 400, 999],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 100,
        "top": 400,
        "width": 201,
        "height": 401,
    }


def test_normalizes_doubao_three_number_point_fallback():
    """normalizes doubao three-number point fallback"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200, 300],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result == {"center": (100, 400), "rect": None}


def test_normalizes_doubao_point_fallback():
    """normalizes doubao point fallback"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result == {"center": (100, 400), "rect": None}


def test_normalizes_doubao_bbox_with_space_separated_point_strings():
    """normalizes doubao bbox with space-separated point strings"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        ["123 100", "789 222"],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 123,
        "top": 200,
        "width": 667,
        "height": 245,
    }


def test_normalizes_doubao_bbox_with_comma_separated_point_strings():
    """normalizes doubao bbox with comma-separated point strings"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        ["123,100", "789, 222"],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 123,
        "top": 200,
        "width": 667,
        "height": 245,
    }


def test_flattens_single_nested_doubao_bbox():
    """flattens single nested doubao bbox"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [[100, 200, 300, 400]],
        {"preparedSize": {"width": 400, "height": 900}},
    )
    assert result["rect"] == {
        "left": 40,
        "top": 180,
        "width": 81,
        "height": 181,
    }


def test_flattens_nested_doubao_bbox_list_by_taking_the_first_entry():
    """flattens nested doubao bbox list by taking the first entry"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [
            [100, 200, 300, 400],
            [100, 200, 300, 400],
        ],
        {"preparedSize": {"width": 400, "height": 900}},
    )
    assert result["rect"] == {
        "left": 40,
        "top": 180,
        "width": 81,
        "height": 181,
    }


def test_normalizes_doubao_malformed_six_number_point_fallback():
    """normalizes doubao malformed six-number point fallback"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200, 300, 400, 100, 200],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result == {"center": (100, 400), "rect": None}


def test_normalizes_doubao_polygon_bbox():
    """normalizes doubao polygon bbox"""
    codec = _vision_locate_codec()
    result = codec.to_pixel_result(
        [100, 200, 300, 200, 300, 400, 100, 400],
        {"preparedSize": {"width": 1000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 100,
        "top": 400,
        "width": 201,
        "height": 401,
    }


def test_throws_on_invalid_doubao_bbox_data():
    """throws on invalid doubao bbox data"""
    codec = _vision_locate_codec()
    with pytest.raises(ValueError):
        codec.to_pixel_result(
            [100],
            {"preparedSize": {"width": 1000, "height": 2000}},
        )
