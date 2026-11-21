"""Element locate system prompt (upstream prompt/locate/element-system-prompt.ts)."""

from midscene.core.ai_model.prompt.locate.grounding_rules import (
    locate_grounding_rules,
)


def build_element_locate_system_prompt(
    system_prompt_introduction: str, response_instructions: str
) -> str:
    return f"""
{system_prompt_introduction}

{locate_grounding_rules()}

{response_instructions}"""


__all__ = ["build_element_locate_system_prompt"]
