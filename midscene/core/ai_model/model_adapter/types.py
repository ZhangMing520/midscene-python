"""Type aliases shared by model adapters (upstream ai-model/model-adapter/types.ts)."""

from typing import Any

ModelRequestUserConfig = dict[str, Any]

ReasoningInput = dict[str, Any]


class ModelRuntime:
    """A model config bound to its family adapter (upstream ModelRuntime)."""

    def __init__(self, config: dict[str, Any], adapter: Any | None = None):
        self.config = config
        if adapter is None:
            from midscene.core.ai_model.models.registry import get_model_adapter

            adapter = get_model_adapter(config.get("modelFamily"))
        self.adapter = adapter
        self.on_usage = None  # optional callback(AIUsageInfo)
        self.model_fallback: dict[str, Any] | None = None
        self._execution_id: str | None = None

    @property
    def execution_id(self) -> str:
        """Stable per-runtime call id sent as `x-midscene-execution-id`."""
        if self._execution_id is None:
            import uuid

            self._execution_id = f"unscoped-{uuid.uuid4().hex}"
        return self._execution_id

    @property
    def model_family(self) -> str | None:
        return self.config.get("modelFamily")

    @property
    def model_name(self) -> str | None:
        return self.config.get("modelName")


__all__ = ["ModelRequestUserConfig", "ModelRuntime", "ReasoningInput"]
