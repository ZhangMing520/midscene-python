"""Synced from the marker/crop helpers in upstream shared image tests.

Sources:
  packages/shared/tests/unit-test/image/index.test.ts   (compositePointMarkerImg, cropByRect)
  packages/shared/tests/unit-test/transform.test.ts      (crop normalization)

The upstream fixtures (icon.png, heytea.jpeg) are generated with Pillow here so
the ported assertions (dimensions, fractional crops) stay identical.
"""

import base64
import io

import pytest
from PIL import Image

from midscene.shared.img.box_select import composite_point_marker
from midscene.shared.img.info import image_info_of_base64
from midscene.shared.img.transform import crop_by_rect


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _jpeg(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(
        buffer, format="JPEG"
    )
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_composite_point_marker_keeps_image_dimensions_and_marks_a_point():
    base64_image = _png(68, 56)

    marked_base64 = composite_point_marker(
        base64_image, {"x": 20, "y": 20}
    )

    assert ";base64," in marked_base64
    assert marked_base64 != base64_image
    assert image_info_of_base64(marked_base64) == image_info_of_base64(
        base64_image
    )


@pytest.mark.skip(
    reason="Python composite_point_marker has no indexId blue callout; it draws "
    "a white/red ring only, so the upstream red/blue reticle assertions do not apply"
)
def test_composite_point_marker_uses_red_and_blue_centered_reticle_markers_without_covering_the_target_point():
    pass


def test_crop_by_rect():
    base64_image = _jpeg(400, 905)

    payload, size = crop_by_rect(
        base64_image,
        {"left": 200, "top": 80, "width": 100, "height": 400},
    )

    assert payload
    assert image_info_of_base64(payload) == {"width": 100, "height": 400}
    assert size == {"width": 100, "height": 400}


def test_crop_by_rect_normalizes_fractional_browser_coordinates():
    base64_image = _jpeg(400, 905)

    payload, size = crop_by_rect(
        base64_image,
        {"left": 200.4, "top": 80.8, "width": 100.7, "height": 40.6},
    )

    assert size == {"width": 101, "height": 41}
    assert image_info_of_base64(payload) == {"width": 101, "height": 41}
