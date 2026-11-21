"""Model adapters and protocols (upstream ai-model/model-adapter)."""

from midscene.core.ai_model.model_adapter.resolve import ModelAdapter
from midscene.core.ai_model.model_adapter.types import ModelRuntime

__all__ = ["ModelAdapter", "ModelRuntime"]
