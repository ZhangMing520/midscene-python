"""Jev planning state/image context (upstream models/jev/planning-context.ts)."""

from typing import Any, Dict, List, Optional
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.shared.multimodal_prompt import get_screenshot_base64

from midscene.core.ai_model.models.jev.image import (
    prepare_jev_image,
)

async def prepare_jev_planning_context(
    instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: Any,
    action_context: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
) -> Dict[str, Any]:
    screenshot = prepare_jev_image(get_screenshot_base64(context))
    state = {
        "goal": instruction,
        "context": action_context,
        "history": conversation_history.historical_logs_to_text(),
        "memory": conversation_history.memories_to_text(),
        "feedback": conversation_history.pending_feedback_message,
        "availableActions": [
            {"name": action.name, "description": action.description}
            for action in action_space
        ],
    }
    images = {"screenshot": screenshot}
    references = []
    for index, url in enumerate(reference_images or []):
        key = f"reference_{index}"
        images[key] = prepare_jev_image(url)
        references.append({"image": f"`{key}`"})
    state["references"] = references
    return {"state": state, "images": images}
