"""AI context rendering (upstream agent/prompt-context.ts)."""

from typing import Any, Optional
from midscene.core.ai_model.models.registry import ModelRuntime


def _render_context_block(context: Optional[str]) -> Optional[str]:
    if context is None:
        return None
    trimmed = context.strip()
    if trimmed:
        return f"<CONTEXT>\n{trimmed}\n</CONTEXT>"
    return ""


def build_locate_prompt_with_context(prompt: Any, context: Optional[str]) -> Any:
    """Attach user guidance to a locate prompt (upstream buildLocatePromptWithContext)."""
    rendered = _render_context_block(context)
    if not rendered:
        return prompt
    prompt_text = prompt if isinstance(prompt, str) else prompt.get("prompt")
    prompt_with_context = (
        f"{rendered}\n\n<LOCATE_TARGET>\n{prompt_text}\n</LOCATE_TARGET>"
    )
    if isinstance(prompt, str):
        return prompt_with_context
    return {**prompt, "prompt": prompt_with_context}


def format_locate_model_context(model_runtime: ModelRuntime) -> str:
    config = model_runtime.config
    return (
        f"modelName={config.get('modelName') or 'unset'} "
        f"modelFamily={config.get('modelFamily') or 'unset'}"
    )


def render_ai_context(context: Any) -> Optional[str]:
    """Render the UIContext's element list as text context for insight calls
    (upstream agent/prompt-context.ts renderAIContext)."""
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
