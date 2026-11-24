"""Per-intent model config manager (upstream packages/shared/src/env/model-config-manager.ts)."""

import os
from typing import TYPE_CHECKING, Any

from midscene.shared.env.constants import (
    MODEL_CONFIG_DOC_URL,
)
from midscene.shared.env.parse_model_config import (
    decide_model_config_from_intent_config,
    model_family_required_for_locate_message,
)
from midscene.shared.env.types import (
    TIntent,
)

if TYPE_CHECKING:
    from midscene.shared.env.global_config_manager import GlobalConfigManager


class ModelConfigManager:
    """Resolve per-intent model configs (default/locate/insight/planning).

    Ported from upstream model-config-manager.ts. Each intent slot falls back to
    the default slot when its dedicated env keys are absent.
    """

    def __init__(
        self,
        model_config: dict[str, str | int | float] | None = None,
        env_provider: dict[str, str | None] | None = None,
    ):
        self.model_config = model_config
        self.env_provider = env_provider
        self._model_config_map: dict[TIntent, dict] | None = None
        self._isolated = model_config is not None
        self.global_config_manager: GlobalConfigManager | None = None

    @property
    def isolated_mode(self) -> bool:
        return self._isolated

    def _get_env(self, key: str) -> str | None:
        if self.env_provider is not None:
            return self.env_provider.get(key)
        if self.global_config_manager is not None:
            return self.global_config_manager.get_all_env_config().get(key)
        return os.environ.get(key)

    def _all_env(self) -> dict[str, str | None]:
        if self.env_provider is not None:
            return dict(self.env_provider)
        if self.global_config_manager is not None:
            return dict(self.global_config_manager.get_all_env_config())
        return dict(os.environ)

    def _initialize(self) -> None:
        if self._model_config_map is not None:
            return

        if self.model_config is not None:
            config_map: dict[str, str | None] = {
                str(k): None if v is None else str(v)
                for k, v in self.model_config.items()
            }
        else:
            config_map = self._all_env()

        default_config = decide_model_config_from_intent_config("default", config_map)
        if default_config is None:
            raise ValueError(
                "Model configuration is incomplete: model name (MIDSCENE_MODEL_NAME) "
                f"is required. See {MODEL_CONFIG_DOC_URL}"
            )

        insight_config = decide_model_config_from_intent_config("insight", config_map)
        planning_config = decide_model_config_from_intent_config("planning", config_map)
        locate_config = decide_model_config_from_intent_config("locate", config_map)

        def build(intent: TIntent, specific: dict | None) -> dict:
            config = dict(specific if specific is not None else default_config)
            config["intent"] = intent
            config["slot"] = intent if specific is not None else "default"
            return config

        self._model_config_map = {
            "default": build("default", default_config),
            "locate": build("locate", locate_config),
            "insight": build("insight", insight_config),
            "planning": build("planning", planning_config),
        }

    def get_model_config(self, intent: TIntent) -> dict:
        self._initialize()
        assert self._model_config_map is not None
        return self._model_config_map[intent]

    def clear_model_config_map(self) -> None:
        if self._isolated:
            raise RuntimeError(
                "ModelConfigManager work in isolated mode, so clear_model_config_map "
                "should not be called"
            )
        self._model_config_map = None

    def throw_error_if_non_vl_model(self) -> None:
        model_config = self.get_model_config("locate")
        if not model_config.get("modelFamily"):
            raise ValueError(
                model_family_required_for_locate_message(model_config["slot"])
            )

    def register_global_config_manager(self, global_config_manager: Any) -> None:
        """Attach the global config manager used in non-isolated mode."""
        self.global_config_manager = global_config_manager

    def get_upload_test_server_url(self) -> str | None:
        model_config = self.get_model_config("default")
        extra = model_config.get("openaiExtraConfig") or {}
        return extra.get("REPORT_SERVER_URL")
