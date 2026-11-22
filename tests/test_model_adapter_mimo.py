"""Synced from upstream packages/core/tests/unit-test/model-adapter/mimo.test.ts."""

import pytest

from midscene.core.ai_model.models.mimo import _build_mimo_params


def _build(base_url=None, user_config=None, expected=False, midscene_defaults=None):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_mimo_params(
        {"temperature": 0.0} if midscene_defaults is None else midscene_defaults,
        user,
        expected,
    )


@pytest.mark.parametrize(
    "base_url,open_router",
    [
        ("https://api.xiaomimimo.com/v1", False),
        ("https://openrouter.ai/api/v1", True),
    ],
    ids=["native", "openrouter"],
)
@pytest.mark.parametrize(
    "reasoning_enabled",
    [None, False, True, "default"],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_enabled_with_endpoint_specific_effort_and_budget_handling(
    base_url, open_router, reasoning_enabled
):
    """maps enabled=%s with endpoint-specific effort and budget handling"""
    result = _build(
        base_url,
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
            "temperature": 0.7,
        },
        True,
    )

    enabled = False if reasoning_enabled is None else reasoning_enabled
    if enabled == "default":
        thinking_config = {}
    elif open_router:
        thinking_config = {
            "reasoning": {
                "enabled": enabled,
                **(
                    {"effort": "high", "max_tokens": 1024}
                    if enabled is True
                    else {}
                ),
            }
        }
    else:
        thinking_config = {
            "thinking": {"type": "enabled" if enabled else "disabled"}
        }

    assert result == {
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        **thinking_config,
    }


def test_defaults_mimo_thinking_to_disabled_when_reasoning_config_is_unset():
    """defaults mimo thinking to disabled when reasoning config is unset"""
    result = _build(user_config={})

    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_preserves_midscene_defaults_and_applies_explicit_mimo_temperature_override():
    """preserves midscene defaults and applies explicit mimo temperature override"""
    result = _build(
        user_config={"temperature": 0.7, "reasoningEnabled": False},
        midscene_defaults={"temperature": 0, "seed": 123},
    )

    assert result == {
        "temperature": 0.7,
        "seed": 123,
        "thinking": {"type": "disabled"},
    }


def test_maps_reasoningenabled_to_thinking_type_for_xiaomi_mimo():
    """maps reasoningEnabled to thinking.type for xiaomi-mimo"""
    disabled_result = _build(user_config={"reasoningEnabled": False})
    enabled_result = _build(user_config={"reasoningEnabled": True})

    assert disabled_result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    assert enabled_result == {
        "temperature": 0,
        "thinking": {"type": "enabled"},
    }


def test_ignores_unsupported_reasoning_effort_and_budget_params():
    """ignores unsupported reasoning effort and budget params"""
    result = _build(
        user_config={"reasoningEffort": "high", "reasoningBudget": 1024}
    )

    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_keeps_user_temperature_in_chat_completion_params():
    """keeps user temperature in chat completion params"""
    result = _build(user_config={"temperature": 0.7})

    assert result == {
        "temperature": 0.7,
        "thinking": {"type": "disabled"},
    }


def test_does_not_set_response_format_without_an_expected_json_object_response():
    """does not set response format without an expected JSON object response"""
    result = _build(user_config={"intent": "default"})

    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_uses_json_object_response_format_when_expected():
    """uses json_object response format when expected"""
    result = _build(
        user_config={"intent": "planning"},
        expected=True,
    )

    assert result["response_format"] == {"type": "json_object"}


def test_does_not_use_json_object_response_format_when_disabled():
    """does not use json_object response format when disabled"""
    result = _build(
        user_config={"responseFormat": "none"},
        expected=True,
    )

    assert "response_format" not in result
