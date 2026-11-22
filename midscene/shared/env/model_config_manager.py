"""Per-intent model config manager (upstream packages/shared/src/env/model-config-manager.ts)."""

from typing import Dict, Optional, Union
import os

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

class ModelConfigManager:
    """Resolve per-intent model configs (default/locate/insight/planning).

    Ported from upstream model-config-manager.ts. Each intent slot falls back to
    the default slot when its dedicated env keys are absent.
    """

    def __init__(
        self,
        model_config: Optional[Dict[str, Union[str, int, float]]] = None,
        env_provider: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.model_config = model_config
        self.env_provider = env_provider
        self._model_config_map: Optional[Dict[TIntent, Dict]] = None
        self._isolated = model_config is not None

    @property
    def isolated_mode(self) -> bool:
        return self._isolated

    def _get_env(self, key: str) -> Optional[str]:
        if self.env_provider is not None:
            return self.env_provider.get(key)
        return os.environ.get(key)

    def _all_env(self) -> Dict[str, Optional[str]]:
        if self.env_provider is not None:
            return dict(self.env_provider)
        return dict(os.environ)

    def _initialize(self) -> None:
        if self._model_config_map is not None:
            return

        if self.model_config is not None:
            config_map: Dict[str, Optional[str]] = {
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
        planning_config = decide_model_config_from_intent_config(
            "planning", config_map
        )
        locate_config = decide_model_config_from_intent_config("locate", config_map)

        def build(intent: TIntent, specific: Optional[Dict]) -> Dict:
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

    def get_model_config(self, intent: TIntent) -> Dict:
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
            raise ValueError(model_family_required_for_locate_message(model_config["slot"]))

    def get_upload_test_server_url(self) -> Optional[str]:
        model_config = self.get_model_config("default")
        extra = model_config.get("openaiExtraConfig") or {}
        return extra.get("REPORT_SERVER_URL")
