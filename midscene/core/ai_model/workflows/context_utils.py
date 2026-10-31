"""Shared helpers for AI workflows (context access + image preparation)."""

import base64
import io
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from ..adapters import ModelRuntime


def user_prompt_to_string(prompt: Any) -> str:
    """TUserPrompt: str or {'prompt': str}."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict) and "prompt" in prompt:
        return str(prompt.get("prompt", ""))
    return str(prompt)


def ensure_data_url(image_base64: str) -> str:
    if image_base64.startswith("data:"):
        return image_base64
    return f"data:image/jpeg;base64,{image_base64}"


def get_screenshot_base64(context: Any) -> str:
    """Read the screenshot from a UIContext (base64 or data URL)."""
    screenshot = getattr(context, "screenshot_base64", None)
    if screenshot is None and isinstance(context, dict):
        screenshot = context.get("screenshot_base64")
    if screenshot is None and isinstance(context, dict):
        nested = context.get("screenshot") or {}
        screenshot = nested.get("base64")
    if not screenshot:
        raise ValueError("UIContext has no screenshot for the AI workflow")
    return screenshot


def get_shot_size(context: Any) -> Dict[str, int]:
    """Read the screenshot size {width, height} from a UIContext."""
    size = getattr(context, "size", None)
    if size is None and isinstance(context, dict):
        size = context.get("size")
    if size is not None:
        return {"width": int(size.width), "height": int(size.height)} if hasattr(size, "width") else {
            "width": int(size["width"]),
            "height": int(size["height"]),
        }
    if isinstance(context, dict):
        shot_size = context.get("shotSize")
        if shot_size:
            return dict(shot_size)
    raise ValueError("UIContext has no size for the AI workflow")


def prepare_model_image(
    image_base64: str,
    width: int,
    height: int,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prepare the image for a model call.

    policy: {'padBlockSize': int} pads the image (right/bottom, white) so its
    dimensions are a multiple of the block size, as required by some models
    (e.g. qwen2.5-vl). Returns {image_base64, prepared_size, content_size}.
    """
    prepared_base64 = image_base64
    model_width = width
    model_height = height

    pad_block_size = (policy or {}).get("padBlockSize")
    if pad_block_size:
        try:
            prepared_base64, model_width, model_height = _pad_to_block(
                image_base64, width, height, int(pad_block_size)
            )
        except Exception as e:  # pragma: no cover - fall back to no padding
            logger.warning(f"image padding failed, using original image: {e}")

    return {
        "image_base64": prepared_base64,
        "prepared_size": {"width": model_width, "height": model_height},
        "content_size": {"width": width, "height": height},
    }


def _pad_to_block(
    image_base64: str, width: int, height: int, block_size: int
) -> Tuple[str, int, int]:
    target_width = ((width + block_size - 1) // block_size) * block_size
    target_height = ((height + block_size - 1) // block_size) * block_size
    if target_width == width and target_height == height:
        return image_base64, width, height

    from PIL import Image

    raw = image_base64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    image = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")

    padded = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    padded.paste(image, (0, 0))

    buffer = io.BytesIO()
    padded.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", target_width, target_height


def format_locate_model_context(model_runtime: ModelRuntime) -> str:
    config = model_runtime.config
    return (
        f"modelName={config.get('modelName') or 'unset'} "
        f"modelFamily={config.get('modelFamily') or 'unset'}"
    )
