"""Search-area locate system prompt (upstream prompt/locate/search-area-system-prompt.ts)."""


def build_search_area_locate_system_prompt(
    system_prompt_introduction: str, response_instructions: str
) -> str:
    return f"""
{system_prompt_introduction}

{response_instructions}"""


__all__ = ["build_search_area_locate_system_prompt"]
