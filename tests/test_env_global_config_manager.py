"""Synced from upstream packages/shared/tests/unit-test/env/global-config-manager.test.ts."""

from unittest.mock import Mock

import pytest

from midscene.shared.env import ModelConfigManager
from midscene.shared.env.global_config_manager import GlobalConfigManager


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "MIDSCENE_ADB_PATH",
        "MIDSCENE_CACHE",
        "MIDSCENE_CACHE_MAX_FILENAME_LENGTH",
        "MIDSCENE_MCP_CHROME_PATH",
        "MIDSCENE_MODEL_NAME",
        "MIDSCENE_MODEL_API_KEY",
        "MIDSCENE_MODEL_BASE_URL",
        "MIDSCENE_PREFERRED_LANGUAGE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def _manager() -> GlobalConfigManager:
    manager = GlobalConfigManager()
    manager.register_model_config_manager(ModelConfigManager())
    return manager


# --- overrideAIConfig -------------------------------------------------------


def test_should_throw_if_called_with_invalid_key():
    """should throw if called with invalid key"""
    global_config_manager = _manager()

    with pytest.raises(
        ValueError,
        match="Failed to override AI config, invalid key: MIDSCENE_RUN_DEBUG",
    ):
        global_config_manager.override_ai_config({"MIDSCENE_RUN_DEBUG": "true"})


def test_should_throw_if_called_with_non_string_value():
    """should throw if called with non-string value"""
    global_config_manager = _manager()

    with pytest.raises(
        ValueError,
        match="Failed to override AI config, value for key MIDSCENE_MODEL_NAME "
        "must be a string, but got with type number",
    ):
        global_config_manager.override_ai_config({"MIDSCENE_MODEL_NAME": 123})

    with pytest.raises(
        ValueError,
        match="but got with type boolean",
    ):
        global_config_manager.override_ai_config({"MIDSCENE_MODEL_NAME": True})

    with pytest.raises(
        ValueError,
        match="but got with type object",
    ):
        global_config_manager.override_ai_config({"MIDSCENE_MODEL_NAME": {}})


def test_should_accept_valid_global_env_keys():
    """should accept valid GLOBAL_ENV_KEYS"""
    global_config_manager = _manager()

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/custom/adb/path",
            "MIDSCENE_CACHE": "true",
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH": "200",
            "MIDSCENE_MCP_CHROME_PATH": "/custom/chrome/path",
            "MIDSCENE_PREFERRED_LANGUAGE": "zh-CN",
        }
    )


def test_should_accept_valid_model_env_keys():
    """should accept valid MODEL_ENV_KEYS"""
    global_config_manager = _manager()

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_MODEL_NAME": "gpt-4",
            "MIDSCENE_MODEL_API_KEY": "sk-test-key",
            "MIDSCENE_MODEL_BASE_URL": "https://api.openai.com/v1",
            "OPENAI_API_KEY": "sk-legacy-key",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        }
    )


def test_should_override_config_values_in_non_extend_mode_default(monkeypatch):
    """should override config values in non-extend mode (default)"""
    global_config_manager = _manager()

    monkeypatch.setenv("MIDSCENE_ADB_PATH", "/original/adb/path")
    monkeypatch.setenv("MIDSCENE_CACHE", "false")
    monkeypatch.setenv("MIDSCENE_MODEL_NAME", "gpt-3.5-turbo")

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/override/adb/path",
            "MIDSCENE_CACHE": "true",
            "MIDSCENE_MODEL_NAME": "gpt-4",
        }
    )

    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/override/adb/path"
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True


def test_should_merge_config_values_in_extend_mode(monkeypatch):
    """should merge config values in extend mode"""
    global_config_manager = _manager()

    monkeypatch.setenv("MIDSCENE_ADB_PATH", "/original/adb/path")
    monkeypatch.setenv("MIDSCENE_CACHE", "false")
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "100")

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/override/adb/path",
            "MIDSCENE_CACHE": "true",
        },
        True,
    )

    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/override/adb/path"
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )


def test_should_warn_when_overriding_already_read_keys(monkeypatch):
    """should warn when overriding already read keys"""
    warnings = []
    monkeypatch.setattr(
        "midscene.shared.env.global_config_manager._console_warn",
        warnings.append,
    )
    global_config_manager = _manager()

    global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
    global_config_manager.override_ai_config({"MIDSCENE_ADB_PATH": "/new/adb/path"})

    assert warnings == [
        "Warning: try to override AI config with key MIDSCENE_ADB_PATH "
        ",but it has been read."
    ]


def test_should_handle_multiple_override_calls():
    """should handle multiple override calls"""
    global_config_manager = _manager()

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/first/override",
            "MIDSCENE_CACHE": "true",
        }
    )
    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/first/override"
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/second/override",
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH": "300",
        }
    )
    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/second/override"
    )
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 300
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is False


def test_should_handle_multiple_override_calls_in_extend_mode(monkeypatch):
    """should handle multiple override calls in extend mode"""
    global_config_manager = _manager()

    monkeypatch.setenv("MIDSCENE_ADB_PATH", "/env/adb/path")
    monkeypatch.setenv("MIDSCENE_CACHE", "false")

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/first/override",
            "MIDSCENE_CACHE": "true",
        },
        True,
    )
    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/first/override"
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "/second/override",
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH": "300",
        },
        True,
    )
    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/second/override"
    )
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 300
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True


def test_should_invalidate_cached_config_when_override_is_called(monkeypatch):
    """should invalidate cached config when override is called"""
    global_config_manager = _manager()

    monkeypatch.setenv("MIDSCENE_ADB_PATH", "/original/path")
    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "/original/path"
    )

    global_config_manager.override_ai_config({"MIDSCENE_ADB_PATH": "/new/path"})

    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH") == "/new/path"
    )


def test_should_clear_model_config_map_when_override_is_called():
    """should clear model config map when override is called"""
    model_config_manager = ModelConfigManager()
    clear_spy = Mock(wraps=model_config_manager.clear_model_config_map)
    model_config_manager.clear_model_config_map = clear_spy
    global_config_manager = GlobalConfigManager()
    global_config_manager.register_model_config_manager(model_config_manager)

    global_config_manager.override_ai_config({"MIDSCENE_MODEL_NAME": "gpt-4"})

    clear_spy.assert_called_once()


def test_should_handle_empty_override_config():
    """should handle empty override config"""
    global_config_manager = _manager()

    global_config_manager.override_ai_config({})


# --- getEnvConfigValueAsNumber ---------------------------------------------


@pytest.fixture
def numeric_env(monkeypatch):
    monkeypatch.setenv("MIDSCENE_ADB_PATH", "<test-adb-path>")
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "100")
    monkeypatch.setenv("MIDSCENE_CACHE", "")


def test_should_return_number_for_valid_numeric_string_values(numeric_env):
    """should return number for valid numeric string values"""
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )


def test_should_return_undefined_for_non_numeric_string_values(
    numeric_env, monkeypatch
):
    """should return undefined for non-numeric string values"""
    monkeypatch.setenv("MIDSCENE_ADB_PATH", "not-a-number")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number("MIDSCENE_ADB_PATH")
        is None
    )


def test_should_return_undefined_for_unset_environment_variables(numeric_env):
    """should return undefined for unset environment variables"""
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_PREFERRED_LANGUAGE"
        )
        is None
    )


def test_should_return_undefined_for_empty_string_values(numeric_env, monkeypatch):
    """should return undefined for empty string values"""
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        is None
    )


def test_should_handle_decimal_values(numeric_env, monkeypatch):
    """should handle decimal values"""
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "123.45")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 123.45
    )


def test_should_handle_zero_values(numeric_env, monkeypatch):
    """should handle zero values"""
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "0")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 0
    )


def test_should_handle_negative_values(numeric_env, monkeypatch):
    """should handle negative values"""
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "-100")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == -100
    )


def test_should_trim_whitespace_before_conversion(numeric_env, monkeypatch):
    """should trim whitespace before conversion"""
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "  100  ")
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )


def test_should_work_with_override_config(numeric_env):
    """should work with override config"""
    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )

    global_config_manager.override_ai_config(
        {"MIDSCENE_CACHE_MAX_FILENAME_LENGTH": "200"}
    )

    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 200
    )


def test_should_throw_if_key_is_not_a_supported_numeric_key(numeric_env):
    """should throw if key is not a supported numeric key"""
    global_config_manager = _manager()

    with pytest.raises(
        ValueError,
        match="getEnvConfigValueAsNumber with key MIDSCENE_CACHE is not supported.",
    ):
        global_config_manager.get_env_config_value_as_number("MIDSCENE_CACHE")


# --- getEnvConfigValue ------------------------------------------------------


@pytest.fixture
def string_env(monkeypatch):
    monkeypatch.setenv("MIDSCENE_MODEL_NAME", "<test-model>")
    monkeypatch.setenv("OPENAI_API_KEY", "<test-openai-api-key>")
    monkeypatch.setenv("OPENAI_BASE_URL", "<test-openai-base-url>")
    monkeypatch.setenv("MIDSCENE_CACHE", "")


def test_should_throw_if_key_is_not_supported(string_env):
    """should throw if key is not supported"""
    global_config_manager = _manager()

    with pytest.raises(
        ValueError,
        match="getEnvConfigValue with key MIDSCENE_MODEL_NAME is not supported.",
    ):
        global_config_manager.get_env_config_value("MIDSCENE_MODEL_NAME")

    with pytest.raises(
        ValueError,
        match="getEnvConfigValueAsNumber with key MIDSCENE_MODEL_NAME is not supported.",
    ):
        global_config_manager.get_env_config_value_as_number("MIDSCENE_MODEL_NAME")

    with pytest.raises(
        ValueError,
        match="getEnvConfigInBoolean with key MIDSCENE_MODEL_NAME is not supported",
    ):
        global_config_manager.get_env_config_in_boolean("MIDSCENE_MODEL_NAME")


def test_should_return_the_correct_value_from_process_env(string_env, monkeypatch):
    """should return the correct value from process.env"""
    monkeypatch.setenv("MIDSCENE_ADB_PATH", "<test-adb-path>")
    monkeypatch.setenv("MIDSCENE_CACHE_MAX_FILENAME_LENGTH", "100")
    monkeypatch.setenv("MIDSCENE_CACHE", "true")

    global_config_manager = _manager()

    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "<test-adb-path>"
    )
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True


def test_should_return_the_correct_value_from_override(string_env):
    """should return the correct value from override"""
    global_config_manager = _manager()

    assert global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH") is None
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        is None
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is False

    global_config_manager.override_ai_config(
        {
            "MIDSCENE_ADB_PATH": "<override-adb-path>",
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH": "100",
            "MIDSCENE_CACHE": "true",
        }
    )

    assert (
        global_config_manager.get_env_config_value("MIDSCENE_ADB_PATH")
        == "<override-adb-path>"
    )
    assert (
        global_config_manager.get_env_config_value_as_number(
            "MIDSCENE_CACHE_MAX_FILENAME_LENGTH"
        )
        == 100
    )
    assert global_config_manager.get_env_config_in_boolean("MIDSCENE_CACHE") is True
