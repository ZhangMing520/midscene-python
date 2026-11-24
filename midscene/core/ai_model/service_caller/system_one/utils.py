"""System One image/asset encoding (upstream system-one/utils.ts)."""

import re
import uuid
from typing import Any

from midscene.core.ai_model.service_caller.system_one.schema import SystemOneError


def encode_system_one_images(
    images: dict[str, str] | None, is_openrouter: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Encode reference images into inline parts (OpenRouter) or assets map."""
    assets: dict[str, Any] = {}
    image_state: dict[str, Any] = {}
    for name, data_url in (images or {}).items():
        if is_openrouter:
            # OpenRouter ignores TypeSafe's top-level assets map; send inline
            # image_url parts instead of asset references.
            image_state[name] = {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
            continue
        reference = uuid.uuid4().hex
        match = re.match(r"^data:image/(png|jpe?g);base64,(.+)$", data_url)
        if not match:
            raise SystemOneError(
                "System One images must be prepared PNG or JPEG data URLs"
            )
        assets[reference] = {
            "type": "image",
            "format": "png" if match.group(1) == "png" else "jpg",
            "data_base64": match.group(2),
        }
        image_state[name] = reference
    return image_state, assets


__all__ = ["encode_system_one_images"]
