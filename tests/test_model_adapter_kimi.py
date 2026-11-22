"""Synced from upstream packages/core/tests/unit-test/model-adapter/kimi.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.models.kimi import _build_kimi3_params, _build_kimi_params
from midscene.core.ai_model.models.registry import get_model_adapter


def _build_kimi(base_url=None, user_config=None, expected=False):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_kimi_params({"temperature": 0.0}, user, expected)


def _build_kimi3(base_url=None, user_config=None, expected=False):
    user = dict(user_config or {})
    if base_url is not None:
        user["baseURL"] = base_url
    return _build_kimi3_params({"temperature": 0.0}, user, expected)


def _kimi_locate_codec():
    locate = resolve_locate(get_model_adapter("kimi"))
    assert locate["kind"] == "standard"
    return locate["element"]["result_codec"]


@pytest.mark.parametrize(
    "base_url,open_router",
    [
        ("https://api.moonshot.cn/v1", False),
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
    result = _build_kimi(
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

    # Kimi disallows custom temperature, so the key is omitted.
    assert result == {
        "response_format": {"type": "json_object"},
        **thinking_config,
    }


def test_uses_0_1_normalized_xy_point_coordinates_for_kimi_locate_results():
    """uses 0-1 normalized xy point coordinates for kimi locate results"""
    result = _kimi_locate_codec().to_pixel_result(
        [0.371, 0.109],
        {"preparedSize": {"width": 1920, "height": 1440}},
    )
    assert result == {"center": (712, 157), "rect": None}


def test_accepts_pixel_xy_point_coordinates_for_kimi_locate_results():
    """accepts pixel xy point coordinates for kimi locate results"""
    result = _kimi_locate_codec().to_pixel_result(
        [960, 540],
        {"preparedSize": {"width": 1920, "height": 1080}},
    )
    assert result == {"center": (960, 540), "rect": None}


def test_accepts_pixel_xy_point_strings_for_kimi_locate_results():
    """accepts pixel xy point strings for kimi locate results"""
    result = _kimi_locate_codec().to_pixel_result(
        "960 540",
        {"preparedSize": {"width": 1920, "height": 1080}},
    )
    assert result == {"center": (960, 540), "rect": None}


@pytest.mark.parametrize(
    "point",
    [[0.5, 0.5, 0.5], [960, 540, 100], "960 540 100"],
    ids=["normalized-extra", "pixel-extra", "string-extra"],
)
def test_rejects_kimi_point_results_with_extra_coordinates(point):
    """rejects Kimi point results with extra coordinates: $point"""
    codec = _kimi_locate_codec()
    with pytest.raises(ValueError, match="invalid point data"):
        codec.to_pixel_result(
            point,
            {"preparedSize": {"width": 1920, "height": 1080}},
        )


def test_rejects_out_of_range_kimi_pixel_point_coordinates():
    """rejects out-of-range kimi pixel point coordinates"""
    codec = _kimi_locate_codec()
    with pytest.raises(ValueError, match="exceed image size"):
        codec.to_pixel_result(
            [2000, 540],
            {"preparedSize": {"width": 1920, "height": 1080}},
        )


def test_defaults_kimi_thinking_to_disabled_when_reasoning_config_is_unset():
    """defaults kimi thinking to disabled when reasoning config is unset"""
    result = _build_kimi(user_config={})

    assert result == {"thinking": {"type": "disabled"}}


def test_preserves_midscene_defaults_while_removing_kimi_temperature():
    """preserves midscene defaults while removing kimi temperature"""
    result = _build_kimi_params(
        {"temperature": 0, "seed": 123},
        {"temperature": 0.7, "reasoningEnabled": True},
    )

    # Kimi disallows custom temperature, so the key is omitted.
    assert result == {
        "seed": 123,
        "thinking": {"type": "enabled"},
    }


def test_maps_reasoningenabled_to_thinking_type_for_kimi():
    """maps reasoningEnabled to thinking.type for kimi"""
    result = _build_kimi(user_config={"reasoningEnabled": True})

    assert result == {"thinking": {"type": "enabled"}}


def test_ignores_unsupported_reasoning_effort_and_budget_params():
    """ignores unsupported reasoning effort and budget params"""
    result = _build_kimi(
        user_config={"reasoningEffort": "high", "reasoningBudget": 1024}
    )

    assert result == {"thinking": {"type": "disabled"}}


def test_removes_user_temperature_from_chat_completion_params():
    """removes user temperature from chat completion params"""
    result = _build_kimi(user_config={"temperature": 0.7})

    assert result == {"thinking": {"type": "disabled"}}


def test_uses_json_object_response_format_when_expected_for_kimi():
    """uses json_object response format when expected for kimi"""
    result = _build_kimi(user_config={}, expected=True)

    assert result["response_format"] == {"type": "json_object"}


def test_does_not_use_json_object_response_format_when_disabled():
    """does not use json_object response format when disabled"""
    result = _build_kimi(
        user_config={"responseFormat": "none"},
        expected=True,
    )

    assert "response_format" not in result


@pytest.mark.parametrize(
    "reasoning_enabled,expected",
    [
        (None, {"reasoning": {"enabled": False}}),
        (False, {"reasoning": {"enabled": False}}),
        (
            True,
            {"reasoning": {"enabled": True, "effort": "high", "max_tokens": 1024}},
        ),
        ("default", {}),
    ],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_openrouter_enabled_with_effort_and_budget(reasoning_enabled, expected):
    """maps OpenRouter enabled=$reasoningEnabled with effort and budget"""
    result = _build_kimi3(
        "https://openrouter.ai/api/v1",
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "high",
            "reasoningBudget": 1024,
        },
    )

    assert result == expected


def test_omits_empty_openrouter_reasoning_configuration_for_default():
    """omits empty OpenRouter reasoning configuration for default"""
    result = _build_kimi3(
        "https://openrouter.ai/api/v1",
        {"reasoningEnabled": "default"},
    )
    assert result == {}


@pytest.mark.parametrize(
    "reasoning_enabled,expected",
    [
        (None, {"thinking": {"type": "disabled"}}),
        (False, {"thinking": {"type": "disabled"}}),
        (True, {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}),
        ("default", {}),
    ],
    ids=["undefined", "false", "true", "default"],
)
def test_maps_native_enabled_and_effort_without_budget(reasoning_enabled, expected):
    """maps native enabled=$reasoningEnabled and effort without budget"""
    result = _build_kimi3(
        "https://api.moonshot.cn/v1",
        {
            "reasoningEnabled": reasoning_enabled,
            "reasoningEffort": "max",
            "reasoningBudget": 1024,
        },
    )

    assert result == expected


def test_omits_native_thinking_configuration_for_default_without_effort():
    """omits native thinking configuration for default without effort"""
    result = _build_kimi3(user_config={"reasoningEnabled": "default"})
    assert result == {}


def test_replays_the_raw_assistant_message_for_multi_turn_reasoning():
    """replays the raw assistant message for multi-turn reasoning"""
    assert get_model_adapter("kimi3").replay_raw_assistant_message is True
    assert get_model_adapter("kimi").replay_raw_assistant_message is False


def test_disables_native_k3_thinking_when_unset():
    """disables native K3 thinking when unset"""
    result = _build_kimi3(user_config={})

    assert result == {"thinking": {"type": "disabled"}}


def test_maps_reasoning_effort_to_the_kimi_3_top_level_config():
    """maps reasoning effort to the Kimi 3 top-level config"""
    result = _build_kimi3(
        user_config={"reasoningEffort": "max", "reasoningEnabled": True}
    )

    assert result == {
        "reasoning_effort": "max",
        "thinking": {"type": "enabled"},
    }
