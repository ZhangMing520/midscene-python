"""Synced from upstream packages/shared/tests/unit-test/env/parse.test.ts.

The upstream suite targets ``parse-model-config.ts``; the Python counterpart is
``midscene.shared.env.parse_model_config`` (the mapped locate-result parser has
no model-config parsing API).
"""

import pytest

import midscene
from midscene.shared.env import (
    DEFAULT_MODEL_CONFIG_KEYS,
    INSIGHT_MODEL_CONFIG_KEYS,
    LOCATE_MODEL_CONFIG_KEYS,
    MODEL_FAMILY_VALUES,
    PLANNING_MODEL_CONFIG_KEYS,
)
from midscene.shared.env.constants import DEFAULT_MODEL_CONFIG_KEYS_LEGACY
from midscene.shared.env.parse_model_config import (
    get_ui_tars_model_version,
    legacy_config_to_model_family,
    parse_openai_sdk_config,
    validate_model_family,
)

_TIMEOUT_KEY_SETS = [
    DEFAULT_MODEL_CONFIG_KEYS,
    INSIGHT_MODEL_CONFIG_KEYS,
    PLANNING_MODEL_CONFIG_KEYS,
]
_PROTOCOL_KEY_SETS = [
    DEFAULT_MODEL_CONFIG_KEYS,
    INSIGHT_MODEL_CONFIG_KEYS,
    PLANNING_MODEL_CONFIG_KEYS,
]
_TEMPERATURE_KEY_SETS = [
    DEFAULT_MODEL_CONFIG_KEYS,
    INSIGHT_MODEL_CONFIG_KEYS,
    PLANNING_MODEL_CONFIG_KEYS,
    LOCATE_MODEL_CONFIG_KEYS,
]


@pytest.mark.parametrize("keys", _TIMEOUT_KEY_SETS)
def test_leaves_an_unset_timeout_undefined(keys):
    """leaves an unset timeout undefined"""
    assert parse_openai_sdk_config(keys=keys, provider={})["timeout"] is None


@pytest.mark.parametrize("keys", _TIMEOUT_KEY_SETS)
@pytest.mark.parametrize("value", ["0", "1", "180000", "0.5", " 100 "])
def test_accepts_the_finite_non_negative_value(keys, value):
    """accepts the finite non-negative value %s"""
    result = parse_openai_sdk_config(keys=keys, provider={keys["timeout"]: value})
    assert result["timeout"] == float(value)


@pytest.mark.parametrize("keys", _TIMEOUT_KEY_SETS)
@pytest.mark.parametrize(
    "value", ["-1", "NaN", "Infinity", "-Infinity", "abc", "", "   ", "1e309"]
)
def test_rejects_the_invalid_value(keys, value):
    """rejects the invalid value %s"""
    with pytest.raises(
        ValueError,
        match=f"{keys['timeout']} must be a finite number greater than or equal to 0",
    ):
        parse_openai_sdk_config(keys=keys, provider={keys["timeout"]: value})


def test_should_return_undefined_when_model_family_is_missing():
    """should return undefined when model family is missing"""
    assert get_ui_tars_model_version() is None


def test_should_map_ui_tars_variants_to_correct_version():
    """should map ui-tars variants to correct version"""
    assert get_ui_tars_model_version("vlm-ui-tars") == "1.0"
    assert get_ui_tars_model_version("vlm-ui-tars-doubao") == "doubao-1.5-20B"
    assert get_ui_tars_model_version("vlm-ui-tars-doubao-1.5") == "doubao-1.5-20B"


def test_should_return_undefined_for_non_ui_tars_models():
    """should return undefined for non-UI-TARS models"""
    for family in (
        "qwen3-vl",
        "doubao-vision",
        "gemini",
        "glm-v",
        "gpt-5",
        "kimi",
        "xiaomi-mimo",
    ):
        assert get_ui_tars_model_version(family) is None


def test_legacy_default_keys_use_openai_compatible_environment_names():
    """legacy default keys use OpenAI-compatible environment names"""
    assert DEFAULT_MODEL_CONFIG_KEYS_LEGACY["openaiApiKey"] == "OPENAI_API_KEY"
    assert DEFAULT_MODEL_CONFIG_KEYS_LEGACY["openaiBaseURL"] == "OPENAI_BASE_URL"
    assert (
        DEFAULT_MODEL_CONFIG_KEYS_LEGACY["socksProxy"] == "MIDSCENE_OPENAI_SOCKS_PROXY"
    )
    assert DEFAULT_MODEL_CONFIG_KEYS_LEGACY["httpProxy"] == "MIDSCENE_OPENAI_HTTP_PROXY"
    assert (
        DEFAULT_MODEL_CONFIG_KEYS_LEGACY["openaiExtraConfig"]
        == "MIDSCENE_OPENAI_INIT_CONFIG_JSON"
    )
    assert (
        DEFAULT_MODEL_CONFIG_KEYS_LEGACY["modelFamily"]
        == "DEFAULT_MODEL_CONFIG_KEYS has no modelFamily key"
    )
    assert DEFAULT_MODEL_CONFIG_KEYS_LEGACY["timeout"] == "MIDSCENE_MODEL_TIMEOUT"


@pytest.mark.parametrize("family", ["tencent-hy", "qwen4"])
def test_accepts_family_through_model_config_parsing(family):
    """accepts %s through model config parsing"""
    result = parse_openai_sdk_config(
        keys=DEFAULT_MODEL_CONFIG_KEYS,
        provider={"MIDSCENE_MODEL_FAMILY": family},
    )
    assert result["modelFamily"] == family


def test_should_not_throw_on_valid_model_families():
    """should not throw on valid model families"""
    for family in (
        "qwen3-vl",
        "qwen3",
        "qwen3.6",
        "doubao-vision",
        "gemini",
        "glm-v",
        "gpt-5",
        "gpt-6",
        "kimi",
        "xiaomi-mimo",
        "vlm-ui-tars",
        None,
    ):
        validate_model_family(family)


def test_should_throw_on_invalid_value():
    """should throw on invalid value"""
    with pytest.raises(
        ValueError, match="Invalid MIDSCENE_MODEL_FAMILY value: invalid"
    ):
        validate_model_family("invalid")
    with pytest.raises(ValueError, match=f"Current version v{midscene.__version__}"):
        validate_model_family("invalid")
    with pytest.raises(ValueError, match=", ".join(MODEL_FAMILY_VALUES)):
        validate_model_family("invalid")
    with pytest.raises(
        ValueError, match="https://www.midscenejs.com/model-api-setup.html"
    ):
        validate_model_family("invalid")


def test_should_return_undefined_when_no_legacy_vars_set():
    """should return undefined when no legacy vars set"""
    assert legacy_config_to_model_family({}) is None


def test_should_map_individual_legacy_flags_to_model_family():
    """should map individual legacy flags to model family"""
    assert legacy_config_to_model_family({"MIDSCENE_USE_QWEN3_VL": "1"}) == "qwen3-vl"
    assert legacy_config_to_model_family({"MIDSCENE_USE_QWEN_VL": "1"}) == "qwen2.5-vl"
    assert (
        legacy_config_to_model_family({"MIDSCENE_USE_DOUBAO_VISION": "1"})
        == "doubao-vision"
    )
    assert legacy_config_to_model_family({"MIDSCENE_USE_GEMINI": "1"}) == "gemini"


def test_should_handle_ui_tars_legacy_flags():
    """should handle UI-TARS legacy flags"""
    assert (
        legacy_config_to_model_family({"MIDSCENE_USE_VLM_UI_TARS": "1"})
        == "vlm-ui-tars"
    )
    assert (
        legacy_config_to_model_family({"MIDSCENE_USE_VLM_UI_TARS": "DOUBAO"})
        == "vlm-ui-tars-doubao-1.5"
    )


def test_should_throw_when_multiple_legacy_flags_enabled():
    """should throw when multiple legacy flags enabled"""
    with pytest.raises(
        ValueError, match="Only one vision mode can be enabled at a time."
    ):
        legacy_config_to_model_family(
            {"MIDSCENE_USE_QWEN3_VL": "1", "MIDSCENE_USE_QWEN_VL": "1"}
        )


@pytest.mark.parametrize("keys", _TEMPERATURE_KEY_SETS)
def test_preserves_explicit_unset_for_temperature(keys):
    """preserves explicit unset for $temperature"""
    result = parse_openai_sdk_config(
        keys=keys,
        provider={keys["modelName"]: "gpt-5.6-sol", keys["temperature"]: "unset"},
    )
    assert result["temperature"] == "unset"


def test_parses_numeric_temperature():
    """parses numeric temperature"""
    result = parse_openai_sdk_config(
        keys=DEFAULT_MODEL_CONFIG_KEYS,
        provider={
            "MIDSCENE_MODEL_NAME": "gpt-4o",
            "MIDSCENE_MODEL_TEMPERATURE": "0.7",
        },
    )
    assert result["temperature"] == 0.7


def test_ignores_non_numeric_temperature_values():
    """ignores non-numeric temperature values"""
    result = parse_openai_sdk_config(
        keys=DEFAULT_MODEL_CONFIG_KEYS,
        provider={
            "MIDSCENE_MODEL_NAME": "gpt-4o",
            "MIDSCENE_MODEL_TEMPERATURE": "abc",
        },
    )
    assert result["temperature"] is None


@pytest.mark.parametrize("keys", _PROTOCOL_KEY_SETS)
def test_preserves_an_unspecified_protocol(keys):
    """preserves an unspecified protocol"""
    assert parse_openai_sdk_config(keys=keys, provider={})["protocol"] is None


@pytest.mark.parametrize("keys", _PROTOCOL_KEY_SETS)
@pytest.mark.parametrize("value", ["openai-chat", "openai-responses"])
def test_accepts_protocol(keys, value):
    """accepts %s"""
    result = parse_openai_sdk_config(keys=keys, provider={keys["protocol"]: value})
    assert result["protocol"] == value


@pytest.mark.parametrize("keys", _PROTOCOL_KEY_SETS)
@pytest.mark.parametrize(
    "value", ["response", "responses", "chat-completion", "openai-response"]
)
def test_rejects_invalid_protocol_name(keys, value):
    """rejects invalid protocol name %s"""
    with pytest.raises(
        ValueError,
        match=f"{keys['protocol']} must be one of: openai-chat, openai-responses",
    ):
        parse_openai_sdk_config(keys=keys, provider={keys["protocol"]: value})
