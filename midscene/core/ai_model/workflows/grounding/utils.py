"""Grounding workflow helpers (upstream workflows/grounding/utils.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.image_preprocess import (
    ImagePreprocessPolicy,
    PreparedModelImage,
    prepare_model_image,
)
from midscene.core.ai_model.model_adapter.locate_prompt_order import (
    DEFAULT_LOCATE_PROMPT_ORDER,
    build_locate_messages,
    multimodal_prompt_to_messages,
    parse_locate_prompt_order,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.workflows.grounding.types import LocateImage


def prepare_locate_model_input(
    locate_image: LocateImage,
    target_description: Any,
    system_prompt: str,
    user_prompt: str,
    image_preprocess: ImagePreprocessPolicy | None = None,
    prompt_order: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare the locate screenshot and message list for one model call."""
    prepared_image: PreparedModelImage = prepare_model_image(
        image_base64=locate_image["imageBase64"],
        width=locate_image["width"],
        height=locate_image["height"],
        policy=image_preprocess,
    )
    order = prompt_order or parse_locate_prompt_order(DEFAULT_LOCATE_PROMPT_ORDER)
    messages = build_locate_messages(
        order,
        {
            "instructions": system_prompt,
            "screenshot": prepared_image["image_base64"],
            "task": user_prompt,
            "references": multimodal_prompt_to_messages(target_description),
        },
    )
    return {"messages": messages, "prepared_image": prepared_image}


def format_locate_model_context(model_runtime: ModelRuntime) -> str:
    """Describe the bound model for locate parse-error messages."""
    config = model_runtime.config
    return (
        f"modelName={config.get('modelName') or 'unset'} "
        f"modelFamily={config.get('modelFamily') or 'unset'}"
    )


__all__ = ["format_locate_model_context", "prepare_locate_model_input"]
