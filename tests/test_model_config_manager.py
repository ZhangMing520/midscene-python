"""Synced from upstream packages/shared/tests/unit-test/env/modle-config-manager.test.ts,
locate-model.test.ts and parse.test.ts."""

import pytest

from midscene.shared.env import ModelConfigManager


def _config_map(**overrides):
    base = {
        "MIDSCENE_MODEL_NAME": "doubao-seed-1-6",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
    }
    base.update(overrides)
    return base


def test_initializes_default_slot_from_provided_config_map():
    manager = ModelConfigManager(_config_map())

    config = manager.get_model_config("default")

    assert config["modelName"] == "doubao-seed-1-6"
    assert config["intent"] == "default"
    assert config["slot"] == "default"


def test_records_intent_and_slot_when_intent_config_falls_back_to_default():
    manager = ModelConfigManager(_config_map())

    locate_config = manager.get_model_config("locate")

    assert locate_config["modelName"] == "doubao-seed-1-6"
    assert locate_config["slot"] == "default"


def test_accepts_a_dedicated_locate_model():
    manager = ModelConfigManager(
        _config_map(
            MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max",
            MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl",
            MIDSCENE_LOCATE_MODEL_BASE_URL="https://example.com/v1",
            MIDSCENE_LOCATE_MODEL_API_KEY="sk-locate",
        )
    )

    locate_config = manager.get_model_config("locate")

    assert locate_config["modelName"] == "qwen3-vl-max"
    assert locate_config["modelFamily"] == "qwen3-vl"
    assert locate_config["slot"] == "locate"
    # planning still falls back
    assert manager.get_model_config("planning")["slot"] == "default"


def test_maps_individual_legacy_flags_to_model_family():
    manager = ModelConfigManager(_config_map(MIDSCENE_USE_QWEN3_VL="1"))

    assert manager.get_model_config("default")["modelFamily"] == "qwen3-vl"


def test_requires_model_name():
    manager = ModelConfigManager({"MIDSCENE_MODEL_API_KEY": "sk"})

    with pytest.raises(Exception) as exc:
        manager.get_model_config("default")

    assert "MIDSCENE_MODEL_NAME" in str(exc.value)


def test_throws_on_invalid_model_family():
    manager = ModelConfigManager(_config_map(MIDSCENE_MODEL_FAMILY="not-a-family"))

    with pytest.raises(ValueError) as exc:
        manager.get_model_config("default")

    assert "Invalid MIDSCENE_MODEL_FAMILY" in str(exc.value)


def test_throws_when_multiple_legacy_flags_enabled():
    from midscene.shared.env import legacy_config_to_model_family

    with pytest.raises(ValueError):
        legacy_config_to_model_family(
            {"MIDSCENE_USE_QWEN_VL": "1", "MIDSCENE_USE_GEMINI": "1"}
        )


def test_parses_temperature_retry_count_and_timeout():
    manager = ModelConfigManager(
        _config_map(
            MIDSCENE_MODEL_TEMPERATURE="0.5",
            MIDSCENE_MODEL_RETRY_COUNT="2",
            MIDSCENE_MODEL_TIMEOUT="60",
        )
    )

    config = manager.get_model_config("default")

    assert config["temperature"] == 0.5
    assert config["retryCount"] == 2
    assert config["timeout"] == 60


def test_preserves_explicit_unset_temperature():
    manager = ModelConfigManager(_config_map(MIDSCENE_MODEL_TEMPERATURE="unset"))

    assert manager.get_model_config("default")["temperature"] == "unset"


def test_accepts_new_model_families():
    for family in ("step", "tencent-hy", "qwen4"):
        manager = ModelConfigManager(_config_map(MIDSCENE_MODEL_FAMILY=family))
        assert manager.get_model_config("default")["modelFamily"] == family
