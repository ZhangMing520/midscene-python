"""UI context capture and screenshot shrink (upstream agent/screenshot-preparation.ts)."""

import asyncio
import math
from collections.abc import Mapping
from typing import Any, Protocol, cast

from loguru import logger

from midscene.core.agent.common import CONTEXT_RETRY_DELAY_MS, CONTEXT_RETRY_MAX
from midscene.core.types import UIContext
from midscene.shared.img import image_info_of_base64
from midscene.shared.img.transform import (
    convert_base64_image_to_jpeg,
    resize_base64_image_to_jpeg,
)

SCREENSHOT_JPEG_QUALITY = 90


def _assert_valid_size(size: Mapping[str, float], label: str) -> None:
    width = size.get("width")
    height = size.get("height")
    if (
        width is None
        or height is None
        or not math.isfinite(width)
        or not math.isfinite(height)
    ):
        raise ValueError(
            f"Invalid {label}: width and height must be finite numbers. "
            f"Received width: {width}, height: {height}"
        )
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Invalid {label}: width and height must be positive numbers. "
            f"Received width: {width}, height: {height}"
        )


async def prepare_raw_screenshot(
    screenshot_base64: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare one raw screenshot for model context or persistence.

    Each raw screenshot passes through this pipeline at most once.
    """
    options = options or {}
    shrink_factor = options.get("shrinkFactor", options.get("shrink_factor", 1))
    if (
        shrink_factor is None
        or not isinstance(shrink_factor, (int, float))
        or isinstance(shrink_factor, bool)
        or not math.isfinite(shrink_factor)
        or shrink_factor < 1
    ):
        raise ValueError(
            "Invalid screenshotShrinkFactor: must be a finite number >= 1. "
            f"Received: {shrink_factor}"
        )

    original_size = image_info_of_base64(screenshot_base64)
    _assert_valid_size(original_size, "screenshot dimensions")

    if shrink_factor > 1:
        shot_size = {
            "width": int(math.floor(original_size["width"] / shrink_factor + 0.5)),
            "height": int(math.floor(original_size["height"] / shrink_factor + 0.5)),
        }
    else:
        shot_size = dict(original_size)
    _assert_valid_size(shot_size, "prepared screenshot dimensions")

    base64 = resize_base64_image_to_jpeg(
        screenshot_base64,
        {
            "sourceSize": original_size,
            "targetSize": shot_size,
            "jpegQuality": SCREENSHOT_JPEG_QUALITY,
        },
    )
    return {
        "base64": base64,
        "originalSize": original_size,
        "shotSize": shot_size,
    }


async def prepare_screenshot_for_persistence(
    screenshot_base64: str,
    options: dict[str, Any] | None = None,
) -> str:
    """Prepare a screenshot for persistence when only JPEG output is needed."""
    options = options or {}
    shrink_factor = options.get("shrinkFactor", options.get("shrink_factor", 1))
    if shrink_factor == 1:
        return convert_base64_image_to_jpeg(screenshot_base64, SCREENSHOT_JPEG_QUALITY)
    prepared = await prepare_raw_screenshot(screenshot_base64, options)
    return cast(str, prepared["base64"])


class ContextProvider(Protocol):
    async def get_context(self) -> UIContext: ...


class ScreenshotOptions(Protocol):
    screenshot_shrink_factor: float


class ScreenshotAgent(Protocol):
    _frozen: bool
    frozen_context: UIContext | None

    @property
    def options(self) -> ScreenshotOptions: ...

    @property
    def interface(self) -> ContextProvider: ...

    def is_retryable_context_error(self, error: Exception) -> bool: ...

    def _apply_screenshot_shrink(self, context: UIContext) -> UIContext: ...


async def get_ui_context(agent: ScreenshotAgent, action: str = "locate") -> UIContext:
    if agent._frozen and agent.frozen_context is not None:
        return agent.frozen_context
    attempt = 0
    while True:
        try:
            context = await agent.interface.get_context()
            break
        except Exception as e:
            if attempt < CONTEXT_RETRY_MAX and agent.is_retryable_context_error(e):
                logger.debug(
                    "retryable context error "
                    f"(attempt {attempt + 1}/{CONTEXT_RETRY_MAX}), "
                    f"retrying in {CONTEXT_RETRY_DELAY_MS}ms: {e}"
                )
                await asyncio.sleep(CONTEXT_RETRY_DELAY_MS / 1000)
                attempt += 1
                continue
            raise
    context = agent._apply_screenshot_shrink(context)
    if agent._frozen:
        agent.frozen_context = context
    return context


def apply_screenshot_shrink(agent: ScreenshotAgent, context: UIContext) -> UIContext:
    """Record the screenshot-space -> logical-space ratio and downscale the
    screenshot when asked (upstream commonContextParser:
    shrunkShotToLogicalRatio = dpr / screenshotShrinkFactor,
    dpr = physicalWidth / logicalWidth)."""
    factor = float(getattr(agent.options, "screenshot_shrink_factor", 1.0) or 1.0)
    try:
        import base64 as _b64
        import io as _io

        from PIL import Image

        raw = context.screenshot_base64
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[1]
        image = Image.open(_io.BytesIO(_b64.b64decode(raw)))
        physical_width, physical_height = image.size
        logical_width = context.size.width or physical_width
        dpr = physical_width / logical_width if logical_width else 1.0
        ratio = dpr / factor
        if factor <= 1:
            if ratio == 1.0:
                return context
            return context.model_copy(update={"shrunk_shot_to_logical_ratio": ratio})
        target_width = max(1, round(physical_width / factor))
        target_height = max(1, round(physical_height / factor))
        shrunk = image.resize((target_width, target_height))
        buffer = _io.BytesIO()
        shrunk.save(buffer, format="PNG")
        shrunk_base64 = _b64.b64encode(buffer.getvalue()).decode("ascii")
        return context.model_copy(
            update={
                "screenshot_base64": shrunk_base64,
                "shrunk_shot_to_logical_ratio": ratio,
            }
        )
    except Exception as e:
        logger.warning(f"screenshot shrink failed, using original: {e}")
        return context
