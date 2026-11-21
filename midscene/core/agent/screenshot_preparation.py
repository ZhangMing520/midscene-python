"""UI context capture and screenshot shrink (upstream agent/screenshot-preparation.ts)."""

import asyncio
from loguru import logger

from midscene.core.agent.common import CONTEXT_RETRY_DELAY_MS, CONTEXT_RETRY_MAX
from midscene.core.types import UIContext

async def get_ui_context(agent, action: str = "locate") -> UIContext:
    if agent._frozen and agent.frozen_context is not None:
        return agent.frozen_context
    attempt = 0
    while True:
        try:
            context = await agent.interface.get_context()
            break
        except Exception as e:
            if (
                attempt < CONTEXT_RETRY_MAX
                and agent.is_retryable_context_error(e)
            ):
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


def apply_screenshot_shrink(agent, context: UIContext) -> UIContext:
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
            return context.model_copy(
                update={"shrunk_shot_to_logical_ratio": ratio}
            )
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
