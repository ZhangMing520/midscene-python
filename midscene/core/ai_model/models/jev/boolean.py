"""Jev boolean workflow (upstream models/jev/boolean.ts)."""

from typing import Any, Dict, Optional
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.system_one import SystemOneError, call_system_one
from midscene.core.ai_model.shared.multimodal_prompt import get_screenshot_base64

from midscene.core.ai_model.models.jev.image import (
    prepare_jev_image,
)

async def jev_boolean(
    statement: str,
    context: Any,
    model_runtime: ModelRuntime,
    page_description: str = "",
    context_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Jev boolean: returns {value, raw_response, usage}."""
    screenshot = prepare_jev_image(get_screenshot_base64(context))
    result = await call_system_one(
        model_runtime,
        {
            "state": {
                "statement": statement,
                "context": context_text,
                "pageDescription": page_description,
                "frames": ["`frame_0`"],
            },
            "images": {"frame_0": screenshot},
            "questions": {
                "result": {
                    "type": "noul",
                    "instructions": (
                        "Is `statement` true? Screenshots in `frames` are ordered "
                        "earliest to latest. For current state use the latest "
                        "frame; for events use the relevant frames. Reference "
                        "images are supporting context, not screenshots, unless "
                        "the statement requests comparison. Use the provided "
                        "context and page description when present."
                    ),
                }
            },
        },
    )
    answers = result["answers"]
    if answers["result"]["type"] != "noul":
        raise SystemOneError("Invalid Jev boolean answer")
    return {
        "value": answers["result"]["noul"] >= 0.5,
        "raw_response": result["content"],
        "usage": result["usage"],
    }
