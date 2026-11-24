"""Planning prompts.

Synced from upstream packages/core/src/ai-model/prompt/planning/*
(system-prompt.ts, action-space-description.ts, action-output-example.ts,
planning-response-example.ts, sub-goals-text.ts, multi-turn-example.ts).
"""

from midscene.core.ai_model.prompt.planning.action_output_example import (
    build_action_output_example,
    create_sample_input_action,
    create_sample_tap_action,
)
from midscene.core.ai_model.prompt.planning.action_space_description import (
    build_locate_field_description,
    build_planning_action_space_description,
    serialize_action_descriptions,
)
from midscene.core.ai_model.prompt.planning.multi_turn_example import (
    build_planning_multi_turn_example,
)
from midscene.core.ai_model.prompt.planning.planning_response_example import (
    build_planning_response_example,
)
from midscene.core.ai_model.prompt.planning.sub_goals_text import build_sub_goals_text
from midscene.core.ai_model.prompt.planning.system_prompt import (
    build_standard_planning_system_prompt,
)
from midscene.shared.env import (
    planning_model_family_required_for_locate_message,  # noqa: F401 re-export
)

__all__ = [
    "build_action_output_example",
    "build_locate_field_description",
    "build_planning_action_space_description",
    "build_planning_multi_turn_example",
    "build_planning_response_example",
    "build_standard_planning_system_prompt",
    "build_sub_goals_text",
    "create_sample_input_action",
    "create_sample_tap_action",
    "serialize_action_descriptions",
]
