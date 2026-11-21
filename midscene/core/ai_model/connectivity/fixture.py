"""Fixture image used by the connectivity test.

Synced from upstream packages/core/src/ai-model/connectivity/fixture.ts.
The upstream fixture is an embedded form screenshot; Python renders a small
synthetic form so the image stays readable without a binary asset.
"""

import base64
import io
from functools import lru_cache
from typing import Dict

CONNECTIVITY_FIXTURE_SHOT_SIZE: Dict[str, int] = {"width": 320, "height": 100}


@lru_cache(maxsize=1)
def connectivity_fixture_image() -> str:
    """A lazily rendered form-like fixture as a PNG data URL."""
    from PIL import Image, ImageDraw

    width = CONNECTIVITY_FIXTURE_SHOT_SIZE["width"]
    height = CONNECTIVITY_FIXTURE_SHOT_SIZE["height"]
    image = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle([16, 20, 200, 44], outline=(120, 120, 120), width=2)
    draw.rectangle([16, 60, 280, 84], outline=(120, 120, 120), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


__all__ = ["CONNECTIVITY_FIXTURE_SHOT_SIZE", "connectivity_fixture_image"]
