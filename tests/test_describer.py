"""Tests for the element describer and the screenshot marker helpers."""

import base64
import io

import pytest
from PIL import Image

from midscene.shared.img.box_select import (
    composite_point_marker,
    composite_rect_marker,
)
from midscene.shared.img.transform import (
    crop_by_rect as crop_image,
    image_size,
    resize_long_edge,
)
from midscene.core.element_describer import (
    build_locate_validator_result,
    describe_element_at_point,
    verify_element_description_at_point,
    verify_locator,
)
from midscene.core.types import NodeType, Rect, Size, UIContext, UINode, UITree


def _png_base64(width: int = 100, height: int = 80) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _decode(payload: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(payload.split(",", 1)[1]))).convert("RGB")


class _FakeAgent:
    def __init__(self, context: UIContext):
        self._context = context
        self.runtime_requests = []

    def _resolve_runtime(self, task_type: str):
        self.runtime_requests.append(task_type)
        return {"taskType": task_type}

    async def get_context(self) -> UIContext:
        return self._context


def _context(width: int = 200, height: int = 150) -> UIContext:
    return UIContext(
        screenshot_base64=_png_base64(width, height),
        size=Size(width=width, height=height),
        content=[],
        tree=UITree(
            node=UINode(
                id="root",
                content="",
                rect=Rect(left=0.0, top=0.0, width=width, height=height),
                center=(width / 2, height / 2),
                node_type=NodeType.CONTAINER,
            )
        ),
    )


class TestImageOps:
    def test_point_marker_keeps_size_and_draws_at_the_point(self):
        payload = composite_point_marker(_png_base64(), {"x": 50, "y": 40})
        assert payload.startswith("data:image/jpeg;base64,")
        assert image_size(payload) == {"width": 100, "height": 80}
        marked = _decode(payload)
        ring = marked.getpixel((50, 40 - 14))
        assert sum(ring) < 700  # the white border/red ring replaced white pixels

    def test_rect_marker_keeps_size(self):
        payload = composite_rect_marker(
            _png_base64(), {"left": 10, "top": 10, "width": 40, "height": 20}
        )
        assert image_size(payload) == {"width": 100, "height": 80}

    def test_crop_clamps_to_image_bounds(self):
        payload, size = crop_image(
            _png_base64(), {"left": 80, "top": 60, "width": 15, "height": 10}
        )
        assert size == {"width": 15, "height": 10}
        assert image_size(payload) == size
        # An oversized rect is clamped back into the image like upstream clampRect.
        _, full_size = crop_image(
            _png_base64(), {"left": 80, "top": 60, "width": 500, "height": 500}
        )
        assert full_size == {"width": 100, "height": 80}

    def test_resize_only_upscales_small_crops(self):
        assert resize_long_edge(_png_base64(2000, 1000)) is None
        upscaled = resize_long_edge(_png_base64(100, 50))
        assert upscaled is not None
        assert image_size(upscaled) == {"width": 200, "height": 100}


class TestDescribeMessages:
    def test_light_describe_sends_one_marked_screenshot(self, monkeypatch):
        from midscene.core.service import describe

        monkeypatch.setattr(
            describe.box_select,
            "composite_point_marker",
            lambda image, point, radius=14: f"marked:{point['x']},{point['y']}",
        )
        messages = describe.build_describe_messages(
            "shot", [50, 60], {"width": 100, "height": 100}
        )

        assert messages[0]["role"] == "system"
        content = messages[1]["content"]
        assert content[1] == {"type": "image", "url": "marked:50.0,60.0"}

    def test_deep_describe_appends_a_marked_crop(self, monkeypatch):
        from midscene.core.service import describe

        monkeypatch.setattr(
            describe.box_select,
            "composite_point_marker",
            lambda image, point, radius=14: f"marked:{image}",
        )
        monkeypatch.setattr(
            describe.transform,
            "crop_by_rect",
            lambda image, rect: ("crop", {"width": 10, "height": 10}),
        )
        monkeypatch.setattr(
            describe.transform, "resize_long_edge", lambda image, *args: "resized"
        )
        messages = describe.build_describe_messages(
            "shot", [50, 60], {"width": 100, "height": 100}, deep_describe=True
        )

        content = messages[1]["content"]
        assert content[2] == {"type": "image", "url": "marked:shot"}
        assert "Image 2" in content[3]["text"]
        assert content[4] == {"type": "image", "url": "resized"}


class TestLocateValidator:
    def test_passes_when_center_is_close(self):
        result = build_locate_validator_result([100, 100], {"center": [105, 104]})
        assert result["pass"] is True
        assert result["centerDistance"] == 6

    def test_passes_when_point_is_inside_the_rect(self):
        result = build_locate_validator_result(
            [100, 100],
            {
                "center": [160, 160],
                "rect": {"left": 80, "top": 80, "width": 60, "height": 60},
            },
        )
        assert result["pass"] is True
        assert result["includedInRect"] is True

    def test_fails_when_far_away(self):
        result = build_locate_validator_result([10, 10], {"center": [100, 100]})
        assert result["pass"] is False

    def test_threshold_is_configurable(self):
        result = build_locate_validator_result(
            [10, 10], {"center": [40, 10]}, center_distance_threshold=40
        )
        assert result["pass"] is True


class TestDescribeElementAtPoint:
    @pytest.mark.asyncio
    async def test_describes_and_verifies(self, monkeypatch):
        from midscene.core import element_describer

        calls = []

        async def fake_describe(context, target, runtime, deep_describe=False):
            calls.append({"target": target, "deep": deep_describe})
            return {"description": "the Save button"}

        async def fake_locate(**kwargs):
            return {
                "element": {
                    "center": [102, 101],
                    "rect": {"left": 90, "top": 90, "width": 24, "height": 20},
                }
            }

        monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
        monkeypatch.setattr(element_describer, "locate_service", fake_locate)

        result = await describe_element_at_point(_FakeAgent(_context()), [100, 100])

        assert result["success"] is True
        assert result["prompt"] == "the Save button"
        assert result["verifyResult"]["pass"] is True
        assert result["failureStage"] is None
        assert calls[0]["target"] == [100, 100]

    @pytest.mark.asyncio
    async def test_retries_with_deep_options(self, monkeypatch):
        from midscene.core import element_describer

        deep_flags = []
        locate_calls = []

        async def fake_describe(context, target, runtime, deep_describe=False):
            deep_flags.append(deep_describe)
            return {"description": "the Save button"}

        async def fake_locate(**kwargs):
            locate_calls.append(kwargs.get("deep_locate"))
            center = [300, 300] if len(locate_calls) == 1 else [100, 100]
            return {"element": {"center": center}}

        monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
        monkeypatch.setattr(element_describer, "locate_service", fake_locate)

        result = await describe_element_at_point(_FakeAgent(_context()), [100, 100])

        assert result["success"] is True
        assert deep_flags == [False, True]
        assert locate_calls == [False, True]

    @pytest.mark.asyncio
    async def test_reports_describe_failure(self, monkeypatch):
        from midscene.core import element_describer

        async def fake_describe(context, target, runtime, deep_describe=False):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)

        result = await describe_element_at_point(_FakeAgent(_context()), [10, 10])

        assert result["success"] is False
        assert result["failureStage"] == "describe"
        assert "model unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_verify_only_mode_skips_the_second_locate(self, monkeypatch):
        from midscene.core import element_describer

        async def fake_describe(context, target, runtime, deep_describe=False):
            return {"description": "the Save button"}

        async def fake_locate(**kwargs):
            raise AssertionError("verify must not run")

        monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
        monkeypatch.setattr(element_describer, "locate_service", fake_locate)

        result = await describe_element_at_point(
            _FakeAgent(_context()), [10, 10], {"verify_prompt": False}
        )

        assert result["success"] is True
        assert result["verifyResult"] is None


class TestVerifyLocator:
    @pytest.mark.asyncio
    async def test_raises_when_the_element_is_gone(self, monkeypatch):
        from midscene.core import element_describer

        async def fake_locate(**kwargs):
            return {"element": None, "errors": ["element not found"]}

        monkeypatch.setattr(element_describer, "locate_service", fake_locate)

        with pytest.raises(ValueError, match="Element not found"):
            await verify_locator(_FakeAgent(_context()), "the Save button", [10, 10])

    @pytest.mark.asyncio
    async def test_rejects_empty_descriptions(self):
        with pytest.raises(ValueError, match="must not be empty"):
            await verify_element_description_at_point(
                _FakeAgent(_context()), "   ", [10, 10]
            )