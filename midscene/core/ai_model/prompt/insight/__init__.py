"""Insight (visual understanding / extraction) prompts.

Synced from upstream packages/core/src/ai-model/prompt/insight/*
"""

from midscene.core.ai_model.prompt.insight.system_prompt import (
    build_insight_system_prompt,
)
from midscene.core.ai_model.prompt.insight.user_prompt import (
    build_type_query_demand_value,
    extract_data_query_prompt,
)

__all__ = [
    "build_insight_system_prompt",
    "build_type_query_demand_value",
    "extract_data_query_prompt",
]
