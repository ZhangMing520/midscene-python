"""Insight user prompt (upstream prompt/insight/user-prompt.ts)."""

from typing import Optional, Union


def build_type_query_demand_value(
    demand_type: str, demand: Union[str, dict]
) -> str:
    """Build a typed demand value ('Boolean' | 'Number' | 'String' | 'Assert' | 'WaitFor')."""
    current_screenshot_constraint = (
        "based on the current screenshot and its contents if provided, unless the "
        "user explicitly asks to compare with reference images"
    )

    if demand_type == "Assert":
        return (
            f"Boolean, {current_screenshot_constraint}, whether the following "
            f"statement is true: {demand}"
        )
    if demand_type == "WaitFor":
        return (
            "Boolean, the user wants to do some 'wait for' operation. "
            f"{current_screenshot_constraint}, please check whether the following "
            f"statement is true: {demand}"
        )
    return f"{demand_type}, {current_screenshot_constraint}, {demand}"


def extract_data_query_prompt(
    page_description: str,
    data_query: Union[str, dict],
    context: Optional[str] = None,
) -> str:
    import json as _json

    data_query_text = (
        data_query
        if isinstance(data_query, str)
        else _json.dumps(data_query, indent=2, ensure_ascii=False)
    )

    trimmed_context = context.strip() if context else ""
    context_section = f"\n{trimmed_context}\n" if trimmed_context else ""

    return f"""
<PageDescription>
{page_description}
</PageDescription>{context_section}
<DATA_DEMAND>
{data_query_text}
</DATA_DEMAND>
  """


__all__ = ["build_type_query_demand_value", "extract_data_query_prompt"]
