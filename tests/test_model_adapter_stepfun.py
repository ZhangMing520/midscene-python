"""Synced from upstream packages/core/tests/unit-test/model-adapter/stepfun.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.models.registry import get_model_adapter
from midscene.core.ai_model.models.stepfun import _build_step_params
from midscene.core.ai_model.service_caller.utils import resolve_image_detail


def _build(base_url=None, user_config=None, expected=False):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_step_params({"temperature": 0.0}, user, expected)


def _step_locate_element():
    locate = resolve_locate(get_model_adapter("step"))
    assert locate["kind"] == "standard"
    return locate["element"]


BASE_URLS = [
    ("https://api.stepfun.com/v1", False),
    ("https://openrouter.ai/api/v1", True),
]


@pytest.mark.parametrize(
    "base_url,open_router", BASE_URLS, ids=["native", "openrouter"]
)
@pytest.mark.parametrize(
    "reasoning_enabled",
    [None, False, True, "default"],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_reasoning(base_url, open_router, reasoning_enabled):
    """maps reasoning=%s"""
    config = _build(
        base_url,
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
            "temperature": 0.3,
        },
    )
    effort = "high" if reasoning_enabled is True else "low"
    if reasoning_enabled == "default":
        reasoning = {}
    elif open_router:
        reasoning = {
            "reasoning": {
                "effort": effort,
                **({"max_tokens": 1024} if reasoning_enabled is True else {}),
            }
        }
    else:
        reasoning = {"reasoning_effort": effort}

    assert config == {"temperature": 0.3, **reasoning}


@pytest.mark.parametrize(
    "base_url,open_router", BASE_URLS, ids=["native", "openrouter"]
)
def test_uses_low_by_default_and_medium_when_explicitly_enabled(base_url, open_router):
    """uses low by default and medium when explicitly enabled"""
    for reasoning_enabled in [None, True]:
        config = _build(base_url, {"reasoningEnabled": reasoning_enabled})
        effort = "medium" if reasoning_enabled else "low"
        assert config == {
            "temperature": 0,
            **(
                {"reasoning": {"effort": effort}}
                if open_router
                else {"reasoning_effort": effort}
            ),
        }


@pytest.mark.parametrize(
    "base_url,open_router", BASE_URLS, ids=["native", "openrouter"]
)
@pytest.mark.parametrize(
    "reasoning_budget",
    [None, 0, -1, 1.5, 1024],
    ids=["undefined", "zero", "negative", "float", "positive"],
)
def test_forwards_budget_only_on_openrouter(base_url, open_router, reasoning_budget):
    """forwards budget %s only on OpenRouter"""
    config = _build(
        base_url,
        {
            "reasoningEnabled": True,
            "reasoningEffort": "provider-specific",
            "reasoningBudget": reasoning_budget,
        },
    )

    if open_router:
        expected = {
            "temperature": 0,
            "reasoning": {
                "effort": "provider-specific",
                **(
                    {"max_tokens": reasoning_budget}
                    if reasoning_budget is not None
                    else {}
                ),
            },
        }
    else:
        expected = {
            "temperature": 0,
            "reasoning_effort": "provider-specific",
        }

    assert config == expected


@pytest.mark.parametrize(
    "response_format",
    [None, "none", "auto"],
    ids=["undefined", "none", "auto"],
)
def test_respects_json_mode(response_format):
    """respects JSON mode %s"""
    for expected_json_object_response in [True, False]:
        config = _build(
            user_config={"responseFormat": response_format},
            expected=expected_json_object_response,
        )
        if expected_json_object_response and response_format != "none":
            assert config["response_format"] == {"type": "json_object"}
        else:
            assert "response_format" not in config


def test_keeps_general_tasks_search_areas_and_original_images_available():
    """keeps general tasks, search areas and original images available"""
    adapter = get_model_adapter("step")
    locate = resolve_locate(adapter)

    assert adapter.allowed_task_types is None
    assert adapter.supported_protocols_list == ["openai-chat"]
    assert locate["search_area"] is not None
    assert adapter.image_pad_block_size is None
    assert resolve_image_detail("high", None, False) == "high"


@pytest.mark.parametrize(
    "content",
    [
        '{"point_2d":[484,87]}',
        '```json\n{"point_2d":[484,87]}\n```',
        '{"point":[484,87]}',
    ],
    ids=["point_2d", "fenced", "point-alias"],
)
def test_maps_point_objects_and_field_aliases(content):
    """maps point objects and field aliases: %s"""
    element = _step_locate_element()
    parsed = element["protocol"]["parse_raw_response"](
        content, element["result_codec"].prompt_spec
    )
    assert parsed["kind"] == "located"
    assert element["result_codec"].to_pixel_result(
        parsed["target"], {"preparedSize": {"width": 3000, "height": 2000}}
    ) == {"center": (1452, 174), "rect": None}
    assert element["result_codec"].to_pixel_result(
        parsed["target"], {"preparedSize": {"width": 1500, "height": 1000}}
    )["center"] == (726, 87)


def test_handles_absent_targets_and_rejects_array_responses():
    """handles absent targets and rejects array responses"""
    element = _step_locate_element()
    parse = element["protocol"]["parse_raw_response"]
    prompt_spec = element["result_codec"].prompt_spec

    assert parse('{"point_2d":[],"error":"not visible"}', prompt_spec) == {
        "kind": "not-found",
        "error": "not visible",
    }
    for content in [
        "[]",
        '[{"point_2d":[484,87]}]',
        '[{"point_2d":[1,2]},{"point_2d":[3,4]}]',
        '{"bbox_2d":[1,2,3,4]}',
    ]:
        with pytest.raises(ValueError):
            parse(content, prompt_spec)


def test_rejects_malformed_points_without_guessing_coordinate_scales():
    """rejects malformed points without guessing coordinate scales"""
    codec = _step_locate_element()["result_codec"]
    for point in [
        [1],
        [1, 2, 3, 4],
        [-1, 500],
        [1001, 500],
        [float("nan"), 2],
    ]:
        with pytest.raises(ValueError):
            codec.to_pixel_result(
                point,
                {"preparedSize": {"width": 3000, "height": 2000}},
            )
