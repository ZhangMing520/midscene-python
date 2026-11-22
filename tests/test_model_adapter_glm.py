"""Synced from upstream packages/core/tests/unit-test/model-adapter/glm.test.ts."""

import pytest

from midscene.core.ai_model.models.glm import _build_glm_params


def _build(base_url=None, user_config=None, expected=False, midscene_defaults=None):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_glm_params(
        {"temperature": 0.0} if midscene_defaults is None else midscene_defaults,
        user,
        expected,
    )


@pytest.mark.parametrize(
    "base_url,open_router",
    [
        ("https://open.bigmodel.cn/api/paas/v4", False),
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

    if reasoning_enabled == "default":
        thinking_config = {}
    elif open_router:
        thinking_config = {
            "reasoning": {
                "enabled": reasoning_enabled or False,
                **(
                    {"effort": "high", "max_tokens": 1024}
                    if reasoning_enabled is True
                    else {}
                ),
            }
        }
    else:
        thinking_config = {
            "thinking": {
                "type": "enabled" if reasoning_enabled else "disabled",
            }
        }

    assert result == {
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        **thinking_config,
    }


def test_defaults_glm_v_thinking_to_disabled_when_reasoning_config_is_unset():
    """defaults glm-v thinking to disabled when reasoning config is unset"""
    result = _build(user_config={})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_preserves_midscene_defaults_and_applies_explicit_glm_v_temperature_override():
    """preserves midscene defaults and applies explicit glm-v temperature override"""
    result = _build(
        user_config={"temperature": 0.7, "reasoningEnabled": True},
        midscene_defaults={"temperature": 0, "seed": 123},
    )

    assert result == {
        "temperature": 0.7,
        "seed": 123,
        "thinking": {"type": "enabled"},
    }


def test_maps_reasoningenabled_to_thinking_type_for_glm_v():
    """maps reasoningEnabled to thinking.type for glm-v"""
    result = _build(user_config={"reasoningEnabled": True})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "enabled"},
    }


def test_maps_reasoningenabled_false_to_thinking_type_disabled_for_glm_v():
    """maps reasoningEnabled=false to thinking.type=disabled for glm-v"""
    result = _build(user_config={"reasoningEnabled": False})
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_follows_provider_default_for_glm_v_when_reasoningenabled_default():
    """follows provider default for glm-v when reasoningEnabled=default"""
    result = _build(user_config={"reasoningEnabled": "default"})
    assert result == {"temperature": 0}


def test_ignores_unsupported_reasoning_fields_for_glm_v():
    """ignores unsupported reasoning fields for glm-v"""
    result = _build(
        user_config={"reasoningEffort": "high", "reasoningBudget": 1024}
    )
    assert result == {
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


def test_uses_json_object_response_format_when_expected_for_glm_v():
    """uses json_object response format when expected for glm-v"""
    result = _build(user_config={}, expected=True)

    assert result == {
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }


def test_does_not_use_json_object_response_format_when_disabled():
    """does not use json_object response format when disabled"""
    result = _build(
        user_config={"responseFormat": "none"},
        expected=True,
    )

    assert "response_format" not in result
