"""Locate prompts.

Synced from upstream packages/core/src/ai-model/prompt/locate/*
"""

from midscene.core.ai_model.prompt.locate.element_system_prompt import (
    build_element_locate_system_prompt,
)
from midscene.core.ai_model.prompt.locate.grounding_rules import (
    locate_grounding_rules,
)
from midscene.core.ai_model.prompt.locate.search_area_system_prompt import (
    build_search_area_locate_system_prompt,
)

__all__ = [
    "build_element_locate_system_prompt",
    "build_search_area_locate_system_prompt",
    "locate_grounding_rules",
]
