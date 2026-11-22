"""Synced from upstream packages/core/tests/unit-test/image-preprocess.test.ts."""

import base64
import io

from PIL import Image

from midscene.core.ai_model.model_adapter import image_preprocess
from midscene.core.ai_model.workflows.grounding import build_search_area_config


def _png_data_url(width, height):
    image = Image.new("RGB", (width, height), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_returns_the_original_image_and_size_when_no_padding_policy_is_configured(
    monkeypatch,
):
    """returns the original image and size when no padding policy is configured"""
    calls = []

    def fake_padding(*args):
        calls.append(args)
        raise AssertionError("padding should not be called")

    monkeypatch.setattr(
        image_preprocess, "padding_to_match_block_by_base64", fake_padding
    )

    image = image_preprocess.prepare_model_image(
        image_base64="original-image",
        width=101,
        height=77,
        policy={},
    )

    assert image == {
        "image_base64": "original-image",
        "prepared_size": {"width": 101, "height": 77},
        "content_size": {"width": 101, "height": 77},
    }
    assert calls == []


def test_keeps_content_size_as_the_original_size_after_padding_the_model_image(
    monkeypatch,
):
    """keeps contentSize as the original size after padding the model image"""
    calls = []

    def fake_padding(image_base64, block_size):
        calls.append((image_base64, block_size))
        return {"imageBase64": "padded-image", "width": 112, "height": 84}

    monkeypatch.setattr(
        image_preprocess, "padding_to_match_block_by_base64", fake_padding
    )

    image = image_preprocess.prepare_model_image(
        image_base64="original-image",
        width=101,
        height=77,
        policy={"padBlockSize": 28},
    )

    assert calls == [("original-image", 28)]
    assert image == {
        "image_base64": "padded-image",
        "prepared_size": {"width": 112, "height": 84},
        "content_size": {"width": 101, "height": 77},
    }


def test_crops_the_expanded_area_scales_it_and_records_offset_scale_mapping():
    """crops the expanded area, scales it, and records offset/scale mapping"""
    context = {
        "screenshot_base64": _png_data_url(1000, 800),
        "size": {"width": 1000, "height": 800},
    }

    search_area = build_search_area_config(
        context,
        {"left": 450, "top": 350, "width": 100, "height": 100},
    )

    assert search_area["source_rect"] == {
        "left": 300,
        "top": 200,
        "width": 400,
        "height": 400,
    }
    assert search_area["image"]["width"] == 800
    assert search_area["image"]["height"] == 800
    assert search_area["image"]["imageBase64"].startswith("data:image/jpeg;base64,")
    assert search_area["mapping"] == {
        "offset": {"x": 300, "y": 200},
        "scale": 2,
    }
