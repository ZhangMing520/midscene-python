"""Global config manager and overrides (upstream packages/shared/src/env/global-config-manager.ts)."""

import os
import re
import sys

from midscene.shared.env.constants import (
    ALL_ENV_KEYS,
    BOOLEAN_ENV_KEYS,
    GLOBAL_ENV_KEYS,
    MATCH_BY_POSITION,
    MODEL_ENV_KEYS,
    NUMBER_ENV_KEYS,
    STRING_ENV_KEYS,
)
from midscene.shared.env.model_config_manager import (
    ModelConfigManager,
)


def _console_warn(message: str) -> None:
    print(message, file=sys.stderr)


def _js_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (dict, list, tuple, set)):
        return "object"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


class GlobalConfigManager:
    """Collect global configs from env and ``overrideAIConfig``."""

    def __init__(self, env_provider: dict[str, str | None] | None = None):
        self._env_provider = env_provider
        self._override: dict[str, object] | None = None
        self._keys_have_been_read: dict[str, bool] = {}
        self._global_model_config_manager: ModelConfigManager | None = None

    def _env(self, key: str) -> str | None:
        if self._env_provider is not None:
            return self._env_provider.get(key)
        return os.environ.get(key)

    def get_all_env_config(self) -> dict[str, str | None]:
        """Recalculate the merged env config on every call."""
        env_config = {key: self._env(key) for key in ALL_ENV_KEYS}
        if self._override is not None:
            new_config = self._override.get("newConfig") or {}
            if self._override.get("extendMode"):
                return {**env_config, **new_config}
            return dict(new_config)
        return env_config

    def get_env_config_value(self, key: str) -> str | None:
        all_config = self.get_all_env_config()
        if key == MATCH_BY_POSITION:
            raise ValueError(
                "MATCH_BY_POSITION is discarded, use MIDSCENE_MODEL_FAMILY instead"
            )
        if key not in STRING_ENV_KEYS:
            raise ValueError(f"getEnvConfigValue with key {key} is not supported.")
        self._keys_have_been_read[key] = True
        value = all_config.get(key)
        if isinstance(value, str):
            return value.strip()
        return value

    def get_env_config_in_boolean(self, key: str) -> bool:
        all_config = self.get_all_env_config()
        if key not in BOOLEAN_ENV_KEYS:
            raise ValueError(f"getEnvConfigInBoolean with key {key} is not supported")
        self._keys_have_been_read[key] = True
        value = all_config.get(key)
        if not value:
            return False
        if re.match(r"^(true|1)$", value, re.IGNORECASE):
            return True
        if re.match(r"^(false|0)$", value, re.IGNORECASE):
            return False
        return bool(value.strip())

    def get_env_config_value_as_number(self, key: str) -> int | float | None:
        if key not in STRING_ENV_KEYS and key not in NUMBER_ENV_KEYS:
            raise ValueError(
                f"getEnvConfigValueAsNumber with key {key} is not supported."
            )
        all_config = self.get_all_env_config()
        self._keys_have_been_read[key] = True
        value = all_config.get(key)
        if not isinstance(value, str):
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            parsed = float(trimmed)
        except ValueError:
            return None
        if parsed != parsed:  # NaN
            return None
        return parsed

    def register_model_config_manager(
        self, global_model_config_manager: ModelConfigManager
    ) -> None:
        self._global_model_config_manager = global_model_config_manager

    def override_ai_config(
        self,
        new_config: dict[str, object],
        extend_mode: bool = False,
    ) -> None:
        for key, value in new_config.items():
            if key not in GLOBAL_ENV_KEYS and key not in MODEL_ENV_KEYS:
                raise ValueError(f"Failed to override AI config, invalid key: {key}")
            if not isinstance(value, str):
                raise ValueError(
                    f"Failed to override AI config, value for key {key} must be "
                    f"a string, but got with type {_js_type(value)}"
                )
            if self._keys_have_been_read.get(key):
                _console_warn(
                    f"Warning: try to override AI config with key {key} "
                    ",but it has been read."
                )

        saved_new_config = (
            {**(self._override or {}).get("newConfig", {}), **new_config}
            if extend_mode
            else new_config
        )

        self._override = {
            "newConfig": dict(saved_new_config),
            "extendMode": extend_mode,
        }

        if self._global_model_config_manager is None:
            raise ValueError(
                "globalModelConfigManager is not registered, which should not happen"
            )
        self._global_model_config_manager.clear_model_config_map()


_global_global_config_manager = GlobalConfigManager()


def get_global_config_manager() -> GlobalConfigManager:
    return _global_global_config_manager


_global_model_config_manager = ModelConfigManager()


def get_global_model_config_manager() -> ModelConfigManager:
    return _global_model_config_manager


def reset_global_model_config() -> None:
    """Re-read env on next use (used after override_ai_config)."""
    _global_model_config_manager.clear_model_config_map()


def override_ai_config(
    new_config: dict[str, str | int | float], extend_mode: bool = False
) -> None:
    """Override global model config (mirrors upstream overrideAIConfig)."""
    global _global_model_config_manager
    if extend_mode:
        merged = dict(_global_model_config_manager.model_config or {})
        merged.update(new_config)
        _global_model_config_manager = ModelConfigManager(merged)
    else:
        _global_model_config_manager = ModelConfigManager(dict(new_config))
