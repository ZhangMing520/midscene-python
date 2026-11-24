"""Synced from upstream packages/core/tests/unit-test/model-adapter/tencent-hy.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.model_adapter.planning import resolve_planning
from midscene.core.ai_model.models.registry import get_model_adapter
from midscene.core.ai_model.models.tencent_hy import _build_tencent_hy_params
from midscene.core.ai_model.service_caller.utils import extract_content_and_reasoning


def _build(base_url=None, user_config=None, expected=False):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_tencent_hy_params({"temperature": 0.0}, user, expected)


def test_disables_thinking_by_default():
    """disables thinking by default"""
    assert _build() == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_maps_enabled_thinking_and_effort():
    """maps enabled thinking and effort"""
    assert _build(
        user_config={
            "reasoningEnabled": True,
            "reasoningEffort": "high",
            "temperature": 0.5,
        }
    ) == {
        "temperature": 0.5,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def test_preserves_provider_defaults_when_requested():
    """preserves provider defaults when requested"""
    assert _build(user_config={"reasoningEnabled": "default"}) == {
        "temperature": 0,
    }


def test_does_not_let_effort_or_budget_enable_disabled_thinking():
    """does not let effort or budget enable disabled thinking"""
    assert _build(
        user_config={
            "reasoningEnabled": False,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
        }
    ) == {"temperature": 0, "thinking": {"type": "disabled"}}


def test_omits_native_effort_and_budget_when_using_provider_defaults():
    """omits native effort and budget when using provider defaults"""
    assert _build(
        "https://tokenhub.tencentmaas.com/v1",
        {
            "reasoningEnabled": "default",
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
        },
    ) == {"temperature": 0}


@pytest.mark.parametrize(
    "reasoning_enabled",
    [None, False, True, "default"],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_openrouter_reasoning_enabled_state(reasoning_enabled):
    """maps OpenRouter reasoning enabled state: %s"""
    result = _build(
        "https://openrouter.ai/api/v1",
        {"reasoningEnabled": reasoning_enabled},
    )
    assert result == {
        "temperature": 0,
        **(
            {}
            if reasoning_enabled == "default"
            else {"reasoning": {"enabled": reasoning_enabled or False}}
        ),
    }


@pytest.mark.parametrize("reasoning_enabled", [None, False], ids=["undefined", "false"])
def test_omits_openrouter_effort_and_budget_when_thinking_is_disabled(
    reasoning_enabled,
):
    """omits OpenRouter effort and budget when thinking is disabled: %s"""
    result = _build(
        "https://openrouter.ai/api/v1",
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
        },
    )
    assert result == {"temperature": 0, "reasoning": {"enabled": False}}


@pytest.mark.parametrize(
    "reasoning_enabled", [True, "default"], ids=["true", "default"]
)
def test_applies_openrouter_effort_and_budget_only_when_explicitly_enabled(
    reasoning_enabled,
):
    """applies OpenRouter effort and budget only when explicitly enabled: %s"""
    result = _build(
        "https://openrouter.ai/api/v1",
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
            "temperature": 0.5,
        },
    )
    assert result == {
        "temperature": 0.5,
        **(
            {"reasoning": {"enabled": True, "effort": "high", "max_tokens": 1024}}
            if reasoning_enabled is True
            else {}
        ),
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "https://tokenhub.tencentmaas.com/v1",
        "https://openrouter.ai.example.com/v1",
        "https://example.com/openrouter.ai",
    ],
    ids=["tokenhub", "openrouter-subdomain", "path"],
)
def test_keeps_native_thinking_parameters_for(base_url):
    """keeps native thinking parameters for %s"""
    assert _build(base_url) == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_extracts_reasoning_content_without_treating_it_as_a_locate_answer():
    """extracts reasoning_content without treating it as a locate answer"""
    adapter = get_model_adapter("tencent-hy")
    assert extract_content_and_reasoning(
        {
            "role": "assistant",
            "content": '{"box_2d":[100,200,300,400]}',
            "refusal": None,
            "reasoning_content": "reasoning text",
        },
        adapter.reasoning_content_keys,
    ) == {
        "content": '{"box_2d":[100,200,300,400]}',
        "reasoning_content": "reasoning text",
    }
    assert adapter.use_reasoning_as_content_fallback is False


def test_shares_normalized_xyxy_boxes_across_element_area_and_planning():
    """shares normalized xyxy boxes across element, area and planning"""
    adapter = get_model_adapter("tencent-hy")
    locate = resolve_locate(adapter)
    planning = resolve_planning(adapter)

    assert locate["kind"] == "standard"
    assert locate["search_area"] is not None
    assert planning["kind"] == "standard"

    for operation in [locate["element"], locate["search_area"]]:
        prompt_spec = operation["result_codec"].prompt_spec
        assert prompt_spec["resultKey"] == "box_2d"
        assert operation["protocol"]["expected_json_object_response"] is True
        result = operation["protocol"]["parse_raw_response"](
            '{"box_2d":[100,200,300,400]}', prompt_spec
        )
        assert result == {"kind": "located", "target": [100, 200, 300, 400]}
        assert operation["result_codec"].to_pixel_result(
            result["target"],
            {"preparedSize": {"width": 3000, "height": 2000}},
        ) == {
            # Closed pixel bounds cover 601 x 401 pixels; round the half-pixel center.
            "center": (601, 601),
            "rect": {"left": 300, "top": 400, "width": 601, "height": 401},
        }
        with pytest.raises(ValueError):
            operation["result_codec"].to_pixel_result(
                [100, 200],
                {"preparedSize": {"width": 3000, "height": 2000}},
            )

    assert planning["locate_result_codec"] is locate["element"]["result_codec"]
    assert locate["search_area"]["protocol"]["parse_raw_response"](
        '{"box_2d":[100,200,300,400],"references_box_2d":[[500,600,700,800]]}',
        locate["search_area"]["result_codec"].prompt_spec,
    ) == {
        "kind": "located",
        "target": [100, 200, 300, 400],
        "references": [[500, 600, 700, 800]],
    }
    assert locate["element"]["protocol"]["parse_raw_response"](
        '{"box_2d":[],"error":"not found"}',
        locate["element"]["result_codec"].prompt_spec,
    ) == {"kind": "not-found", "error": "not found"}
