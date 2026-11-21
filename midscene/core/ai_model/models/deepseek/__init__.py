"""DeepSeek adapter and locate protocol (upstream ai-model/models/deepseek/*)."""

from midscene.core.ai_model.models.deepseek.adapter import _build_deepseek_params
from midscene.core.ai_model.models.deepseek.locate_protocol import (
    DEEPSEEK_ELEMENT_LOCATE_FORMAT,
    DEEPSEEK_ELEMENT_LOCATE_PROTOCOL,
    DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT,
    DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL,
)

__all__ = [
    "DEEPSEEK_ELEMENT_LOCATE_FORMAT",
    "DEEPSEEK_ELEMENT_LOCATE_PROTOCOL",
    "DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT",
    "DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL",
    "_build_deepseek_params",
]
