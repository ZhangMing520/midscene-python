"""Synced from upstream packages/core/tests/unit-test/model-adapter/gemini.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.models.gemini import _build_gemini_params
from midscene.core.ai_model.models.registry import get_model_adapter


def _build(user_config=None, midscene_defaults=None, expected=False):
    return _build_gemini_params(
        {"temperature": 0.0} if midscene_defaults is None else midscene_defaults,
        dict(user_config or {}),
        expected,
    )


def _thinking(level):
    return {
        "extra_body": {
            "google": {
                "thinking_config": {
                    "include_thoughts": True,
                    "thinking_level": level,
                }
            }
        }
    }


def _gemini_locate_element():
    locate = resolve_locate(get_model_adapter("gemini"))
    assert locate["kind"] == "standard"
    return locate["element"]


def test_keeps_gemini_bbox_prompt_in_yxyx_order():
    """keeps Gemini bbox prompt in yxyx order"""
    element = _gemini_locate_element()
    assert "[ymin, xmin, ymax, xmax]" in element["result_codec"].prompt_spec[
        "resultValueDescription"
    ]


def test_uses_low_thinking_level_for_gemini_when_reasoning_is_unset():
    """uses low thinking level for gemini when reasoning is unset"""
    result = _build()
    assert result == {
        "temperature": 0,
        **_thinking("low"),
    }


def test_preserves_midscene_defaults_and_applies_explicit_gemini_temperature_override():
    """preserves midscene defaults and applies explicit gemini temperature override"""
    result = _build(
        {"temperature": 0.7},
        midscene_defaults={"temperature": 0, "seed": 123},
    )

    assert result == {
        "temperature": 0.7,
        "seed": 123,
        **_thinking("low"),
    }


def test_uses_low_thinking_level_for_insight_intent_by_default():
    """uses low thinking level for insight intent by default"""
    result = _build({"intent": "insight"})
    assert result == {
        "temperature": 0,
        **_thinking("low"),
    }


def test_uses_medium_thinking_level_when_reasoning_is_enabled_without_effort():
    """uses medium thinking level when reasoning is enabled without effort"""
    result = _build({"reasoningEnabled": True})
    assert result == {
        "temperature": 0,
        **_thinking("medium"),
    }


def test_maps_reasoning_effort_to_gemini_thinking_level_when_reasoning_is_enabled():
    """maps reasoning effort to Gemini thinking level when reasoning is enabled"""
    result = _build({"reasoningEnabled": True, "reasoningEffort": "high"})
    assert result == {
        "temperature": 0,
        **_thinking("high"),
    }


def test_preserves_an_explicitly_requested_minimal_effort_when_reasoning_is_enabled():
    """preserves an explicitly requested minimal effort when reasoning is enabled"""
    result = _build({"reasoningEnabled": True, "reasoningEffort": "minimal"})
    assert result == {
        "temperature": 0,
        **_thinking("minimal"),
    }


def test_uses_low_thinking_level_and_ignores_effort_when_reasoning_is_disabled():
    """uses low thinking level and ignores effort when reasoning is disabled"""
    result = _build({"reasoningEnabled": False, "reasoningEffort": "high"})
    assert result == {
        "temperature": 0,
        **_thinking("low"),
    }


def test_follows_provider_default_and_ignores_effort_for_gemini_when_reasoningenabled_default():
    """follows provider default and ignores effort for gemini when reasoningEnabled=default"""
    result = _build({"reasoningEnabled": "default", "reasoningEffort": "high"})
    assert result == {"temperature": 0}


def test_ignores_reasoning_budget_for_gemini_when_reasoning_is_enabled():
    """ignores reasoning budget for gemini when reasoning is enabled"""
    result = _build({"reasoningEnabled": True, "reasoningBudget": 1024})
    assert result == {
        "temperature": 0,
        **_thinking("medium"),
    }


def test_maps_reasoning_effort_and_ignores_budget_for_gemini_when_reasoning_is_enabled():
    """maps reasoning effort and ignores budget for gemini when reasoning is enabled"""
    result = _build(
        {
            "reasoningEnabled": True,
            "reasoningEffort": "medium",
            "reasoningBudget": 1024,
        }
    )
    assert result == {
        "temperature": 0,
        **_thinking("medium"),
    }


def test_ignores_zero_reasoning_budget_for_gemini_when_reasoning_is_enabled():
    """ignores zero reasoning budget for gemini when reasoning is enabled"""
    result = _build({"reasoningEnabled": True, "reasoningBudget": 0})
    assert result == {
        "temperature": 0,
        **_thinking("medium"),
    }


@pytest.mark.skip(
    reason="Python gemini.py does not implement extractGeminiContentAndReasoning "
    "and the adapter layer has no custom message-extraction hook"
)
def test_extracts_inline_thought_xml_from_string_content():
    """extracts inline thought XML from string content"""
    # No Python equivalent: inline <thought> extraction is not implemented.


@pytest.mark.skip(
    reason="Python gemini.py does not implement extractGeminiContentAndReasoning "
    "and the adapter layer has no custom message-extraction hook"
)
@pytest.mark.parametrize(
    "content",
    [
        "Answer: <thought>quoted thought</thought>",
        "Answer:\n<thought>quoted thought</thought>",
    ],
    ids=["same line", "next line"],
)
def test_does_not_extract_thought_tags_after_visible_content(content):
    """does not extract thought tags after visible content: %s"""
    # No Python equivalent: inline <thought> extraction is not implemented.


@pytest.mark.skip(
    reason="Python gemini.py does not implement extractGeminiContentAndReasoning "
    "and the adapter layer has no custom message-extraction hook"
)
def test_preserves_plain_content_and_provider_reasoning_content():
    """preserves plain content and provider reasoning_content"""
    # No Python equivalent: inline <thought> extraction is not implemented.


@pytest.mark.skip(
    reason="Python gemini.py does not implement extractGeminiContentAndReasoning "
    "and the adapter layer has no custom message-extraction hook"
)
def test_combines_inline_thought_xml_with_provider_reasoning_content():
    """combines inline thought XML with provider reasoning_content"""
    # No Python equivalent: inline <thought> extraction is not implemented.


def test_normalizes_gemini_yxyx_bbox_coordinates():
    """normalizes gemini yxyx bbox coordinates"""
    element = _gemini_locate_element()
    result = element["result_codec"].to_pixel_result(
        [100, 150, 200, 250],
        {"preparedSize": {"width": 2000, "height": 2000}},
    )
    assert result["rect"] == {
        "left": 300,
        "top": 200,
        "width": 201,
        "height": 201,
    }
