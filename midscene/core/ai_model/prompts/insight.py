"""Insight (visual understanding / extraction) prompts.

Synced from upstream packages/core/src/ai-model/prompt/insight/*
"""

from typing import Optional, Union

from ..env_config import get_preferred_language


def _build_insight_context_prompt(
    screenshot_included: bool, reference_images_included: bool
) -> str:
    context_prompts = [
        "The user will give you data requirements in <DATA_DEMAND>. You need to "
        "understand the user's requirements and extract the data satisfying the "
        "<DATA_DEMAND>."
    ]

    if screenshot_included:
        context_prompts.append(
            "The user will provide a current screenshot to evaluate, and may "
            "provide its contents. Base your answer on the current screenshot and "
            "its contents when provided. Treat them as the primary source of "
            "truth for what is currently visible or true."
        )
    else:
        context_prompts.append(
            "The user will not provide a current screenshot. Use only the "
            "supplied page contents and other inputs, and do not infer "
            "unsupported visual details."
        )

    if reference_images_included:
        reference_images_prompt = (
            "Reference images are supporting context only unless <DATA_DEMAND> "
            "explicitly asks for comparison, matching, or reasoning about them."
        )
        context_prompts.append(
            (
                f"{reference_images_prompt} Do not conclude that something exists "
                "in the current screenshot solely because it appears in a "
                "reference image; when they conflict, trust the current screenshot "
                "and its contents."
            )
            if screenshot_included
            else (
                f"{reference_images_prompt} Do not treat reference images as "
                "direct evidence of the current state unless the demand "
                "explicitly asks you to use them that way."
            )
        )

    return "\n\n".join(context_prompts)


def build_insight_system_prompt(
    insight_protocol,
    screenshot_included: bool = True,
    reference_images_included: bool = False,
) -> str:
    """Build the insight system prompt.

    insight_protocol: an object with `response_prefix` and `data_output`
    (with `rules`, `placeholder`, `build_example`).
    """
    preferred_language = get_preferred_language()
    response_prefix = insight_protocol.get("response_prefix") or ""
    data_output = insight_protocol["data_output"]

    context_prompt = _build_insight_context_prompt(
        screenshot_included, reference_images_included
    )

    data_rules = f"\n\n{data_output['rules']}" if data_output.get("rules") else ""
    prefix_text = response_prefix if response_prefix else ""
    build_example = data_output["build_example"]
    example_1 = build_example('{\n  "name": "John",\n  "age": 30,\n  "isAdmin": true\n}')
    example_2 = build_example('["todo 1", "todo 2", "todo 3"]')
    example_3 = build_example('"todo list"')
    example_4 = build_example('{ "StatementIsTruthy": true }')

    return f"""
You are a versatile professional in software UI design and testing. Your outstanding contributions will impact the user experience of billions of users.

{context_prompt}

If a key specifies a JSON data type (such as Number, String, Boolean, Object, Array), ensure the returned value strictly matches that data type.

When DATA_DEMAND is a JSON object, the keys in your response must exactly match the keys in DATA_DEMAND. Do not rename, translate, or substitute any key.{data_rules}


Return in the following XML format:
{prefix_text}
<observation>brief evidence observed for the extraction, less than 300 words. Use {preferred_language} in this field.</observation>
{data_output['placeholder']}
<errors>optional error messages as JSON array, e.g., ["error1", "error2"]</errors>

# Example 1
For example, if the DATA_DEMAND is:

<DATA_DEMAND>
{{
  "name": "name shows on the left panel, string",
  "age": "age shows on the right panel, number",
  "isAdmin": "if the user is admin, boolean"
}}
</DATA_DEMAND>

By viewing the screenshot and page contents, you can extract the following data:

{prefix_text}
<observation>According to the screenshot, i can see ...</observation>
{example_1}

# Example 2
If the DATA_DEMAND is:

<DATA_DEMAND>
the todo items list, string[]
</DATA_DEMAND>

By viewing the screenshot and page contents, you can extract the following data:

{prefix_text}
<observation>According to the screenshot, i can see ...</observation>
{example_2}

# Example 3
If the DATA_DEMAND is:

<DATA_DEMAND>
the page title, string
</DATA_DEMAND>

By viewing the screenshot and page contents, you can extract the following data:

{prefix_text}
<observation>According to the screenshot, i can see ...</observation>
{example_3}

# Example 4
If the DATA_DEMAND is:

<DATA_DEMAND>
{{
  "StatementIsTruthy": "Boolean, is it currently the SMS page?"
}}
</DATA_DEMAND>

By viewing the screenshot and page contents, you can extract the following data:

{prefix_text}
<observation>According to the screenshot, i can see ...</observation>
{example_4}
"""


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
