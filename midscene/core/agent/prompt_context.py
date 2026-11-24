"""AI context rendering (upstream agent/prompt-context.ts)."""

from typing import Any


def render_ai_context(context: str | None) -> str | None:
    """Wrap user guidance in <CONTEXT> tags (upstream renderAIContext).

    ``None`` stays ``None`` (omitted), while an explicitly blank string stays
    blank (empty string).
    """
    if context is None:
        return None
    trimmed = context.strip()
    if trimmed:
        return f"<CONTEXT>\n{trimmed}\n</CONTEXT>"
    return ""


def build_prompt_with_context(prompt: Any, context: str | None) -> Any:
    """Prepend rendered context to a user prompt (upstream buildPromptWithContext)."""
    rendered = render_ai_context(context)
    if not rendered:
        return prompt
    prompt_text = prompt if isinstance(prompt, str) else prompt.get("prompt")
    prompt_with_context = f"{rendered}\n\n{prompt_text}"
    if isinstance(prompt, str):
        return prompt_with_context
    return {**prompt, "prompt": prompt_with_context}


def build_locate_prompt_with_context(prompt: Any, context: str | None) -> Any:
    """Attach user guidance to a locate prompt (upstream buildLocatePromptWithContext)."""
    rendered = render_ai_context(context)
    if not rendered:
        return prompt
    prompt_text = prompt if isinstance(prompt, str) else prompt.get("prompt")
    prompt_with_context = (
        f"{rendered}\n\n<LOCATE_TARGET>\n{prompt_text}\n</LOCATE_TARGET>"
    )
    if isinstance(prompt, str):
        return prompt_with_context
    return {**prompt, "prompt": prompt_with_context}


def format_locate_model_context(model_runtime: Any) -> str:
    """Deprecated re-export of the grounding workflow helper."""
    from midscene.core.ai_model.workflows.grounding.utils import (
        format_locate_model_context as _format,
    )

    return _format(model_runtime)


def render_page_element_context(context: Any) -> str | None:
    """Render a UIContext's visible elements as text for DOM-included calls."""
    elements = getattr(context, "content", None)
    if not elements:
        return None
    lines = []
    for element in elements:
        if not getattr(element, "is_visible", True):
            continue
        element_id = getattr(element, "id", "")
        content = getattr(element, "content", "")
        node_type = getattr(element, "node_type", "")
        rect = getattr(element, "rect", None)
        if rect is not None:
            rect_text = (
                f"rect=({int(getattr(rect, 'left', 0))},"
                f"{int(getattr(rect, 'top', 0))},"
                f"{int(getattr(rect, 'width', 0))}x"
                f"{int(getattr(rect, 'height', 0))})"
            )
        else:
            rect_text = ""
        text = str(content).replace("\n", " ").strip()
        if not text:
            continue
        lines.append(
            f"id={element_id} type={node_type} {rect_text} text={text}".strip()
        )
    if not lines:
        return None
    return "### Page element context (extracted from the UI tree)\n" + "\n".join(lines)


__all__ = [
    "build_locate_prompt_with_context",
    "build_prompt_with_context",
    "format_locate_model_context",
    "render_ai_context",
    "render_page_element_context",
]
