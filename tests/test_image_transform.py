"""Image transform and annotation helpers.

Sources:
  packages/shared/tests/unit-test/transform.test.ts
  packages/shared/tests/unit-test/image/index.test.ts
  packages/shared/tests/unit-test/image/resize-base64-image-to-jpeg.test.ts

Upstream fixtures (icon.png, heytea.jpeg, 2x2.png) are generated with Pillow
here so the ported assertions (dimensions, formats, pixel markers) stay
identical. Node-only cases (sharp/Photon backend failures, byte snapshots that
depend on the encoder) are replaced by Pillow-equivalent assertions; see the
docstring of each test.
"""

import base64
import io
import re

import pytest
from PIL import Image

from midscene.shared.img import transform
from midscene.shared.img.box_select import (
    annotate_rects,
    composite_element_info_img,
    composite_point_marker,
    composite_point_marker_img,
    process_image_element_info,
)
from midscene.shared.img.info import (
    image_info_of_base64,
    is_valid_jpeg_image_buffer,
)

# Fixtures shared with the upstream resize-base64-image-to-jpeg tests.
PNG_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAA"
    "CXBIWXMAAAPoAAAD6AG1e1JrAAAAEUlEQVR4nGMQqbiDFTEMpAQAorNDgTX/VEoAAAAA"
    "SUVORK5CYII="
)
JPEG_DATA_URL = (
    "data:image/jpeg;base64,/9j/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoM"
    "DAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkU"
    "DQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
    "FBT/wAARCAADAAQDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEA"
    "AAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJ9"
    "AFA4//9k="
)

# 1x1 white pixel JPEG image in base64. Upstream hard-codes these bytes, but
# Pillow rejects them ("broken data stream"), so the same fixture is produced
# with Pillow's JPEG encoder instead.
ONE_PIXEL_WHITE_IMAGE = ""  # replaced after the helpers below


def _png(width: int, height: int, color=(255, 255, 255)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _jpeg(width: int, height: int, color=(200, 200, 200)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _body(data_url: str) -> bytes:
    return base64.b64decode(data_url.split(";base64,", 1)[-1])


ONE_PIXEL_WHITE_IMAGE = _jpeg(1, 1, (255, 255, 255))


def _is_jpeg(data_url: str) -> bool:
    return is_valid_jpeg_image_buffer(_body(data_url))


def _rgb_image(data_url: str):
    return Image.open(io.BytesIO(_body(data_url))).convert("RGB")


def test_composite_point_marker_keeps_image_dimensions_and_marks_a_point():
    base64_image = _png(68, 56)

    marked_base64 = composite_point_marker(base64_image, {"x": 20, "y": 20})

    assert ";base64," in marked_base64
    assert marked_base64 != base64_image
    assert image_info_of_base64(marked_base64) == image_info_of_base64(base64_image)


def test_composite_point_marker_img_uses_red_and_blue_centered_reticle_markers_without_covering_the_target_point():
    """port of compositePointMarkerImg uses red and blue centered reticle
    markers without covering the target point"""
    base64_image = _png(120, 120)

    marked_base64 = composite_point_marker_img(
        {"inputImgBase64": base64_image, "point": {"x": 60, "y": 60}}
    )
    locator_marked_base64 = composite_point_marker_img(
        {
            "inputImgBase64": base64_image,
            "point": {"x": 60, "y": 60},
            "indexId": 2,
        }
    )

    marked = _rgb_image(marked_base64)
    locator = _rgb_image(locator_marked_base64)
    width, height = marked.size
    assert locator.size == marked.size

    def is_red_marker_pixel(r, g, b):
        return r > 160 and g < 140 and b < 140

    red_dominant_pixels = 0
    blue_callout_pixels = 0
    for y in range(height):
        for x in range(width):
            r, g, b = marked.getpixel((x, y))
            if is_red_marker_pixel(r, g, b):
                red_dominant_pixels += 1
            if b > 180 and r < 100 and g > 80:
                blue_callout_pixels += 1

    locator_blue_callout_pixels = 0
    for y in range(height):
        for x in range(width):
            r, g, b = locator.getpixel((x, y))
            if b > 180 and r < 100 and g < 100:
                locator_blue_callout_pixels += 1

    target_r, target_g, target_b = marked.getpixel((60, 60))
    # The reticle ring (radius 14) is centered exactly on the point.
    ring_right = marked.getpixel((74, 60))
    ring_bottom = marked.getpixel((60, 74))
    # Pixels beyond the ring/crosshair area stay untouched.
    outside = marked.getpixel((60, 100))
    assert target_r > 245
    assert target_g > 245
    assert target_b > 245
    assert is_red_marker_pixel(*ring_right) is True
    assert is_red_marker_pixel(*ring_bottom) is True
    assert is_red_marker_pixel(*outside) is False
    assert red_dominant_pixels > 20
    assert blue_callout_pixels == 0
    assert locator_blue_callout_pixels > 20


def test_crop_by_rect():
    base64_image = _jpeg(400, 905)

    payload, size = transform.crop_by_rect(
        base64_image,
        {"left": 200, "top": 80, "width": 100, "height": 400},
    )

    assert payload
    assert image_info_of_base64(payload) == {"width": 100, "height": 400}
    assert size == {"width": 100, "height": 400}


def test_crop_by_rect_normalizes_fractional_browser_coordinates():
    base64_image = _jpeg(400, 905)

    payload, size = transform.crop_by_rect(
        base64_image,
        {"left": 200.4, "top": 80.8, "width": 100.7, "height": 40.6},
    )

    assert size == {"width": 101, "height": 41}
    assert image_info_of_base64(payload) == {"width": 101, "height": 41}


@pytest.mark.parametrize(
    "value,rendered,type_name",
    [
        (1, "1", "number"),
        ({}, "[object Object]", "object"),
        (None, "null", "object"),
    ],
)
def test_pre_process_image_url_rejects_non_string_values(value, rendered, type_name):
    """port of "url is not a string will throw an error".

    Python has no ``undefined``; ``None`` covers the JS ``null`` case.
    """
    with pytest.raises(
        ValueError,
        match=re.escape(
            f"url must be a string, but got {rendered} with type {type_name}"
        ),
    ):
        transform.pre_process_image_url(value, False)


def test_pre_process_image_url_keeps_data_urls():
    """port of "base64 string will not be converted"."""
    assert (
        transform.pre_process_image_url("data:image/png;base64,aaa", False)
        == "data:image/png;base64,aaa"
    )


def test_pre_process_image_url_normalizes_data_url_body():
    """port of "base64 string will be normalized for url-safe model payloads"."""
    assert (
        transform.pre_process_image_url("data:image/png;base64,aaa\r\nbbb ccc", False)
        == "data:image/png;base64,aaabbbccc"
    )


def test_pre_process_image_url_converts_local_file_to_base64(tmp_path):
    """port of "local file path will be converted to base64"."""
    image_path = tmp_path / "2x2.jpeg"
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 255, 255)).save(buffer, format="JPEG")
    image_path.write_bytes(buffer.getvalue())

    result = transform.pre_process_image_url(str(image_path), False)

    assert result == (
        "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode()
    )


def test_pre_process_image_url_keeps_http_urls_by_default():
    """port of "http url will not be converted to base64 by default"."""
    url = "https://github.githubassets.com/favicons/favicon.svg"
    assert transform.pre_process_image_url(url, False) == url


def test_pre_process_image_url_converts_http_urls_when_requested(monkeypatch):
    """port of "http url will be converted to base64 if
    convertHttpImage2Base64 is true"; upstream mocks fetch."""
    mock_data = b"image-data"

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "image/svg+xml"}
        content = mock_data

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(transform.httpx, "Client", FakeClient)

    result = transform.pre_process_image_url(
        "https://github.githubassets.com/favicons/favicon.svg", True
    )

    assert result == (
        "data:image/svg+xml;base64," + base64.b64encode(mock_data).decode()
    )


def test_http_img2_base64(monkeypatch):
    """port of the httpImg2Base64 test (fetch mocked with httpx)."""
    mock_response = b"image-data"

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "image/svg+xml"}
        content = mock_response

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(transform.httpx, "Client", FakeClient)

    result = transform.http_img2_base64("https://example.com/image.svg")

    assert result == (
        "data:image/svg+xml;base64," + base64.b64encode(mock_response).decode()
    )


def test_normalize_base64_image_keeps_existing_data_urls_and_trims_whitespace():
    assert (
        transform.normalize_base64_image(" data:image/png;base64,aaa\r\nbbb ")
        == "data:image/png;base64,aaa\r\nbbb"
    )


def test_normalize_base64_image_wraps_bare_png_base64():
    assert (
        transform.normalize_base64_image(" iVBORw0KGgoaaa\r\nbbb ")
        == "data:image/png;base64,iVBORw0KGgoaaabbb"
    )


def test_normalize_base64_image_wraps_bare_non_png_base64_as_jpeg():
    assert (
        transform.normalize_base64_image(" /9j/4AAQ SkZJRg== ")
        == "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    )


def test_normalize_screenshot_base64_accepts_png_and_jpeg_data_urls():
    assert (
        transform.normalize_screenshot_base64(" data:image/png;base64,aaa\r\nbbb ")
        == "data:image/png;base64,aaabbb"
    )
    assert (
        transform.normalize_screenshot_base64("data:image/jpeg;base64,/9j/4AAQ")
        == "data:image/jpeg;base64,/9j/4AAQ"
    )


def test_normalize_screenshot_base64_normalizes_jpg_data_urls_to_jpeg():
    assert (
        transform.normalize_screenshot_base64("data:image/jpg;base64,/9j/4AAQ")
        == "data:image/jpeg;base64,/9j/4AAQ"
    )


def test_normalize_screenshot_base64_wraps_raw_base64_as_png():
    assert (
        transform.normalize_screenshot_base64(" iVBORw0KGgo aaa\r\nbbb ")
        == "data:image/png;base64,iVBORw0KGgoaaabbb"
    )


def test_normalize_screenshot_base64_uses_the_provided_label_in_errors():
    with pytest.raises(ValueError, match="custom screenshot cannot be empty"):
        transform.normalize_screenshot_base64(" ", {"label": "custom screenshot"})

    with pytest.raises(
        ValueError,
        match=(
            "custom screenshot must be a PNG/JPEG data URI or raw PNG base64 string"
        ),
    ):
        transform.normalize_screenshot_base64(
            "data:image/svg+xml;base64,aaa",
            {"label": "custom screenshot"},
        )


def test_infer_base64_image_format_detects_png_and_falls_back_to_jpeg():
    assert transform.infer_base64_image_format("iVBORw0KGgoaaa") == "png"
    assert transform.infer_base64_image_format("/9j/4AAQSkZJRg==") == "jpeg"


def test_create_img_base64_by_format_strips_line_wrapping():
    assert (
        transform.create_img_base64_by_format("png", "foo")
        == "data:image/png;base64,foo"
    )
    assert (
        transform.create_img_base64_by_format("png", "abc\r\ndef ghi")
        == "data:image/png;base64,abcdefghi"
    )


def test_convert_img_buffer_to_jpeg_rejects_invalid_image_bytes():
    """port of "preserves the Sharp failure..." with the Pillow backend.

    Upstream asserts the Node-specific sharp error message; the Python backend
    reports the same failure shape with the Pillow name instead.
    """
    with pytest.raises(ValueError, match="Failed to convert image to JPEG with Pillow"):
        transform.convert_img_buffer_to_jpeg(b"invalid image")


def test_scale_image_scales_up_by_2x_and_reports_dimensions():
    """port of "should scale up image by 2x and verify dimensions".

    The upstream inline snapshot is encoder-specific (sharp); dimensions and
    the JPEG data URL are asserted here instead.
    """
    result = transform.scale_image(ONE_PIXEL_WHITE_IMAGE, 2)

    assert result["width"] == 2
    assert result["height"] == 2
    assert _is_jpeg(result["imageBase64"])


def test_scale_image_scales_up_by_3x_and_reports_dimensions():
    """port of "should scale up image by 3x and verify dimensions"."""
    result = transform.scale_image(ONE_PIXEL_WHITE_IMAGE, 3)

    assert result["width"] == 3
    assert result["height"] == 3
    assert _is_jpeg(result["imageBase64"])


@pytest.mark.parametrize("scale", [-1, 0])
def test_scale_image_rejects_non_positive_scale(scale):
    with pytest.raises(ValueError, match="Scale factor must be positive"):
        transform.scale_image(ONE_PIXEL_WHITE_IMAGE, scale)


def test_resize_and_convert_img_buffer_preserves_unchanged_format():
    """port of "Sharp no-resize will get original format"."""
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    input_buffer = buffer.getvalue()

    result = transform.resize_and_convert_img_buffer(
        "png", input_buffer, {"width": 2, "height": 2}
    )

    assert result["format"] == "png"
    assert result["buffer"] == input_buffer


def test_resize_and_convert_img_buffer_returns_jpeg_after_resizing():
    """port of "Sharp resize will get jpeg format"."""
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")

    result = transform.resize_and_convert_img_buffer(
        "png", buffer.getvalue(), {"width": 1, "height": 1}
    )

    assert result["format"] == "jpeg"
    assert is_valid_jpeg_image_buffer(result["buffer"])


def test_resize_and_convert_img_buffer_rejects_base64_strings():
    with pytest.raises(
        ValueError, match="inputData is base64, use resizeImgBase64 instead"
    ):
        transform.resize_and_convert_img_buffer(
            "png", "data:image/png;base64,aaa", {"width": 1, "height": 1}
        )


def test_resize_base64_image_to_jpeg_reuses_unchanged_jpeg_bytes():
    """port of "reuses an unchanged JPEG before loading an image backend"."""
    result = transform.resize_base64_image_to_jpeg(
        JPEG_DATA_URL,
        {
            "sourceSize": {"width": 4, "height": 3},
            "targetSize": {"width": 4, "height": 3},
        },
    )

    assert result == JPEG_DATA_URL


def test_resize_base64_image_to_jpeg_rejects_mismatched_source_dimensions():
    """port of "rejects source dimensions that do not match the encoded image"."""
    with pytest.raises(
        ValueError,
        match=("sourceSize 1x1 does not match encoded image dimensions 4x3"),
    ):
        transform.resize_base64_image_to_jpeg(
            JPEG_DATA_URL,
            {
                "sourceSize": {"width": 1, "height": 1},
                "targetSize": {"width": 1, "height": 1},
            },
        )


def test_resize_base64_image_to_jpeg_converts_unchanged_png():
    """port of "converts an unchanged PNG without reading metadata again"."""
    result = transform.resize_base64_image_to_jpeg(
        PNG_DATA_URL,
        {
            "sourceSize": {"width": 8, "height": 6},
            "targetSize": {"width": 8, "height": 6},
        },
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert _is_jpeg(result)
    assert image_info_of_base64(result) == {"width": 8, "height": 6}


def test_resize_base64_image_to_jpeg_resizes_and_encodes_jpeg():
    """port of "resizes to JPEG without reading known source dimensions again"."""
    result = transform.resize_base64_image_to_jpeg(
        PNG_DATA_URL,
        {
            "sourceSize": {"width": 8, "height": 6},
            "targetSize": {"width": 4, "height": 3},
        },
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 4, "height": 3}


def test_resize_base64_image_to_jpeg_reads_encoded_dimensions():
    """port of "reads encoded dimensions without backend metadata when source
    dimensions are not provided"."""
    result = transform.resize_base64_image_to_jpeg(
        PNG_DATA_URL, {"targetSize": {"width": 8, "height": 6}}
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 8, "height": 6}


def test_resize_base64_image_to_jpeg_uses_image_bytes_not_the_mime_header():
    """port of "uses image bytes instead of a misleading MIME header"."""
    mislabeled = PNG_DATA_URL.replace("image/png", "image/jpeg")

    result = transform.resize_base64_image_to_jpeg(
        mislabeled,
        {
            "sourceSize": {"width": 8, "height": 6},
            "targetSize": {"width": 8, "height": 6},
        },
    )

    assert _is_jpeg(result)


def test_resize_base64_image_to_jpeg_applies_the_requested_quality():
    """port of "resizeBase64ImageToJpeg applies the requested JPEG quality"."""
    source = _jpeg(400, 905)
    low_quality = transform.resize_base64_image_to_jpeg(
        source,
        {
            "sourceSize": {"width": 400, "height": 905},
            "targetSize": {"width": 100, "height": 100},
            "jpegQuality": 10,
        },
    )
    high_quality = transform.resize_base64_image_to_jpeg(
        source,
        {
            "sourceSize": {"width": 400, "height": 905},
            "targetSize": {"width": 100, "height": 100},
            "jpegQuality": 90,
        },
    )

    assert low_quality.startswith("data:image/jpeg;base64,")
    assert high_quality.startswith("data:image/jpeg;base64,")
    assert low_quality != high_quality


@pytest.mark.parametrize("jpeg_quality", [0, 101, 10.5, float("nan")])
def test_resize_base64_image_to_jpeg_rejects_invalid_quality(jpeg_quality):
    """port of "resizeBase64ImageToJpeg rejects invalid JPEG quality"."""
    with pytest.raises(ValueError, match="jpegQuality"):
        transform.resize_base64_image_to_jpeg(
            PNG_DATA_URL,
            {
                "sourceSize": {"width": 8, "height": 6},
                "targetSize": {"width": 8, "height": 6},
                "jpegQuality": jpeg_quality,
            },
        )


@pytest.mark.parametrize(
    "target_size",
    [
        {"width": 10.5, "height": 10},
        {"width": 10, "height": float("nan")},
        {"width": float("inf"), "height": 10},
        {"width": 0, "height": 10},
    ],
)
def test_resize_base64_image_to_jpeg_rejects_invalid_target_size(target_size):
    """port of "resizeBase64ImageToJpeg rejects invalid target size"."""
    with pytest.raises(ValueError, match=r"targetSize.*positive integers"):
        transform.resize_base64_image_to_jpeg(
            PNG_DATA_URL,
            {
                "sourceSize": {"width": 8, "height": 6},
                "targetSize": target_size,
            },
        )


@pytest.mark.parametrize(
    "source_size",
    [
        {"width": 10.5, "height": 10},
        {"width": 10, "height": float("nan")},
        {"width": float("inf"), "height": 10},
        {"width": 0, "height": 10},
    ],
)
def test_resize_base64_image_to_jpeg_rejects_invalid_source_size(source_size):
    """port of "resizeBase64ImageToJpeg rejects invalid known source size"."""
    with pytest.raises(ValueError, match=r"sourceSize.*positive integers"):
        transform.resize_base64_image_to_jpeg(
            PNG_DATA_URL,
            {
                "sourceSize": source_size,
                "targetSize": {"width": 8, "height": 6},
            },
        )


def test_constrain_base64_image_to_max_size_returns_bounded_image_unchanged():
    """port of "returns an already bounded image without loading an image
    backend" and "preserves an image already within the bound"."""
    assert (
        transform.constrain_base64_image_to_max_size(PNG_DATA_URL, {"maxSize": 8})
        == PNG_DATA_URL
    )


def test_constrain_base64_image_to_max_size_resizes_longest_edge():
    """port of "parses once and resizes the longest edge while preserving
    aspect ratio"."""
    result = transform.constrain_base64_image_to_max_size(
        PNG_DATA_URL, {"maxSize": 4, "jpegQuality": 82}
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 4, "height": 3}


def test_constrain_base64_image_to_max_size_uses_real_image_bytes():
    """port of "bounds the longest edge with real image bytes"."""
    source = _png(68, 56)

    result = transform.constrain_base64_image_to_max_size(source, {"maxSize": 34})

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 34, "height": 28}


@pytest.mark.parametrize("max_size", [0, -1, 1.5, float("nan")])
def test_constrain_base64_image_to_max_size_rejects_invalid_max_size(
    max_size,
):
    """port of "rejects invalid maxSize %s"."""
    with pytest.raises(ValueError, match="maxSize must be a positive integer"):
        transform.constrain_base64_image_to_max_size(
            PNG_DATA_URL, {"maxSize": max_size}
        )


def test_convert_base64_image_to_jpeg_reuses_jpeg_bytes():
    """port of "reuses JPEG bytes without loading an image backend"."""
    assert transform.convert_base64_image_to_jpeg(JPEG_DATA_URL, 90) == JPEG_DATA_URL


def test_convert_base64_image_to_jpeg_converts_png():
    """port of "converts PNG without reading image dimensions"."""
    result = transform.convert_base64_image_to_jpeg(PNG_DATA_URL, 90)

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 8, "height": 6}


def test_convert_base64_image_to_jpeg_rejects_unsupported_formats():
    gif = (
        "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAA"
        "EAAAICRAEAOw=="
    )
    with pytest.raises(
        ValueError,
        match=("inputBase64 must contain a PNG or JPEG image. Detected: image/gif"),
    ):
        transform.convert_base64_image_to_jpeg(gif)


def test_resize_img_base64_keeps_unchanged_png_input():
    """port of "keeps resizeImgBase64 backward compatible for unchanged PNG"."""
    source = _png(68, 56)

    result = transform.resize_img_base64(source, {"width": 68, "height": 56})

    assert result == source
    assert result.startswith("data:image/png;base64,")


def test_resize_img_base64_keeps_unchanged_jpeg_input():
    """port of "keeps resizeImgBase64 backward compatible for unchanged JPEG"."""
    source = _jpeg(400, 905)

    result = transform.resize_img_base64(source, {"width": 400, "height": 905})

    assert result == source
    assert result.startswith("data:image/jpeg;base64,")


def test_resize_img_base64_returns_jpeg_when_dimensions_change():
    """port of "keeps resizeImgBase64 JPEG output behavior when dimensions
    change"."""
    result = transform.resize_img_base64(_png(68, 56), {"width": 34, "height": 28})

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 34, "height": 28}


def test_padding_to_match_block_by_base64_and_save_base64_image(tmp_path):
    """port of "paddingToMatchBlockByBase64" plus saveBase64Image."""
    result = transform.padding_to_match_block_by_base64(_jpeg(400, 905))

    assert result["width"] == 420
    assert result["height"] == 924

    output_path = tmp_path / "heytea-padded.jpeg"
    transform.save_base64_image(
        {
            "base64Data": result["imageBase64"],
            "outputPath": str(output_path),
        }
    )
    assert is_valid_jpeg_image_buffer(output_path.read_bytes())


def test_padding_to_match_block_by_base64_is_a_no_op_when_aligned():
    source = _png(28, 56)

    result = transform.padding_to_match_block_by_base64(source)

    assert result == {"width": 28, "height": 56, "imageBase64": source}


def test_padding_to_match_block_pads_with_white():
    image = transform.photon_from_base64(_png(10, 5))

    result = transform.padding_to_match_block(image, 28)

    assert result["width"] == 28
    assert result["height"] == 28
    assert result["image"].size == (28, 28)
    assert result["image"].getpixel((27, 27)) == (255, 255, 255, 255)
    assert transform.photon_to_base64(result["image"]).startswith(
        "data:image/jpeg;base64,"
    )


def test_pad_base64_image_to_minimum_size_pads_right_and_bottom():
    result = transform.pad_base64_image_to_minimum_size(_jpeg(10, 5), 20)

    assert result["width"] == 20
    assert result["height"] == 20
    assert image_info_of_base64(result["imageBase64"]) == {
        "width": 20,
        "height": 20,
    }


def test_pad_base64_image_to_minimum_size_is_a_no_op_when_large_enough():
    source = _jpeg(20, 20)

    assert transform.pad_base64_image_to_minimum_size(source, 20) == {
        "imageBase64": source,
        "width": 20,
        "height": 20,
    }


def test_zoom_for_gpt4o_limits_width_and_height():
    assert transform.zoom_for_gpt4o(4000, 1000) == {
        "width": 2048,
        "height": 512,
    }
    assert transform.zoom_for_gpt4o(1000, 2000) == {
        "width": 384,
        "height": 768,
    }
    assert transform.zoom_for_gpt4o(1000, 500) == {
        "width": 1000,
        "height": 500,
    }


def test_local_img2_base64_with_and_without_header(tmp_path):
    image_path = tmp_path / "icon.png"
    image_path.write_bytes(_body(_png(68, 56)))

    with_header = transform.local_img2_base64(str(image_path))
    without_header = transform.local_img2_base64(str(image_path), True)

    assert with_header == "data:image/png;base64," + without_header
    assert image_info_of_base64(with_header) == {"width": 68, "height": 56}


def test_local_img2_base64_uses_svg_mime_type(tmp_path):
    svg_path = tmp_path / "icon.svg"
    svg_path.write_text("<svg></svg>", encoding="utf-8")

    result = transform.local_img2_base64(str(svg_path))

    assert result.startswith("data:image/svg+xml;base64,")


def test_composite_element_info_img_keeps_dimensions_and_draws_boxes():
    source = _png(120, 120)

    result = composite_element_info_img(
        {
            "inputImgBase64": source,
            "elementsPositionInfo": [
                {"rect": {"left": 10, "top": 10, "width": 30, "height": 20}},
                {
                    "rect": {"left": 60, "top": 60, "width": 30, "height": 20},
                    "indexId": 2,
                },
            ],
            "annotationPadding": 0,
        }
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 120, "height": 120}
    assert result != source


def test_composite_element_info_img_resizes_to_the_requested_size():
    result = composite_element_info_img(
        {
            "inputImgBase64": _png(120, 120),
            "elementsPositionInfo": [],
            "size": {"width": 60, "height": 60},
            "centerPoint": True,
        }
    )

    assert image_info_of_base64(result) == {"width": 60, "height": 60}


def test_process_image_element_info_returns_both_compositions():
    source = _png(80, 60)
    rects = [{"rect": {"left": 5, "top": 5, "width": 20, "height": 10}}]

    result = process_image_element_info(
        {
            "inputImgBase64": source,
            "elementsPositionInfo": rects,
            "elementsPositionInfoWithoutText": [],
        }
    )

    assert set(result) == {
        "compositeElementInfoImgBase64",
        "compositeElementInfoImgWithoutTextBase64",
    }
    for value in result.values():
        assert value.startswith("data:image/jpeg;base64,")
        assert image_info_of_base64(value) == {"width": 80, "height": 60}


def test_annotate_rects_draws_numbered_borders_without_resizing():
    source = _png(100, 80)

    result = annotate_rects(
        source,
        [
            {"left": 5, "top": 5, "width": 20, "height": 10},
            {"left": 50, "top": 40, "width": 30, "height": 20},
        ],
        "debug prompt",
    )

    assert result.startswith("data:image/jpeg;base64,")
    assert image_info_of_base64(result) == {"width": 100, "height": 80}
    assert result != source
