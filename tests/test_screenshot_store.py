"""Synced from upstream packages/core/tests/unit-test/screenshot-store.test.ts.

The Python port splits the upstream ``ScreenshotStore`` into
``screenshot_store`` (validation/helpers), ``screenshot_item`` (lazy memory)
and ``report_image_export.ReportImageExporter`` (file writing). Cases that
exercise that composition are ported against those pieces; cases that require
the missing facade (inline dedupe by content, tracking collections, deprecated
aliases, dump companion files) are skipped with the specific reason.
"""

import base64
import re

import pytest

from midscene.core.dump.image_reference import normalize_image_url_ref
from midscene.core.dump.report_image_export import ReportImageExporter
from midscene.core.dump.screenshot_store import parse_base64_image_data_url
from midscene.core.screenshot_item import ScreenshotItem

PNG_BASE64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"


@pytest.mark.asyncio
async def test_releases_memory_after_persist_and_supports_recovery_in_directory_mode(
    tmp_path,
):
    """releases memory after persist and supports recovery in directory mode"""
    report_path = tmp_path / "index.html"
    screenshots_dir = tmp_path / "screenshots"
    item = ScreenshotItem.create(PNG_BASE64, 100)
    exporter = ReportImageExporter(str(report_path), str(screenshots_dir))

    relative_path = f"./screenshots/{exporter.write(item.to_serializable(), PNG_BASE64)}"
    absolute_path = tmp_path / relative_path
    assert absolute_path.exists() is True

    item.mark_persisted_to_path(relative_path, str(absolute_path))

    assert item.has_base64() is False
    ref = item.to_serializable()
    assert ref["storage"] == "file"
    assert "data:image/png;base64," in item.base64


@pytest.mark.asyncio
async def test_shares_bytes_across_observations_and_reference_images_while_keeping_observation_identity(
    tmp_path,
):
    """shares bytes across observations and reference images while keeping observation identity"""
    exporter = ReportImageExporter(
        str(tmp_path / "index.html"), str(tmp_path / "screenshots")
    )
    first = ScreenshotItem.create(PNG_BASE64, 100)
    second = ScreenshotItem.create(PNG_BASE64, 200)
    reference = {
        "type": "midscene_image_url_ref",
        "id": "reference-image",
        "mimeType": "image/png",
        "storage": "inline",
    }

    first_path = exporter.write(first.to_serializable(), PNG_BASE64)
    second_path = exporter.write(second.to_serializable(), PNG_BASE64)
    reference_path = exporter.write(reference, PNG_BASE64)

    assert first.id != second.id
    assert [first.captured_at, second.captured_at] == [100, 200]
    assert first_path == second_path
    assert first_path == reference_path
    assert re.match(r"^[a-f0-9]{64}\.png$", first_path)
    assert len(list((tmp_path / "screenshots").iterdir())) == 1
    assert first.base64 == PNG_BASE64
    assert second.base64 == PNG_BASE64


@pytest.mark.skip(
    reason="Python has no ReportActionDump.serializeToFiles/fromFilesAsInlineJson "
    "companion-file round trip"
)
def test_round_trips_screenshots_through_dump_companion_files():
    """round-trips screenshots through dump companion files"""
    pass


@pytest.mark.asyncio
async def test_deduplicates_same_screenshot_persistence_by_id(tmp_path):
    """deduplicates same screenshot persistence by id"""
    exporter = ReportImageExporter(
        str(tmp_path / "index.html"), str(tmp_path / "screenshots")
    )
    item = ScreenshotItem.create(PNG_BASE64, 100)
    ref = item.to_serializable()

    first = exporter.write(ref, PNG_BASE64)
    (tmp_path / "screenshots" / first).write_text("marker", encoding="utf-8")
    second = exporter.write(ref, PNG_BASE64)

    assert first == second
    assert (tmp_path / "screenshots" / first).read_text(encoding="utf-8") == "marker"


@pytest.mark.skip(
    reason="Python has no ScreenshotStore.persistReferenceImage content-keyed "
    "dedupe that returns the first reference id"
)
@pytest.mark.asyncio
async def test_deduplicates_inline_reference_images_by_content():
    """deduplicates inline reference images by content"""
    pass


@pytest.mark.skip(
    reason="Python has no ScreenshotStore tracking collections to inspect for "
    "full data URLs"
)
@pytest.mark.asyncio
async def test_does_not_retain_full_reference_image_data_urls_in_tracking_collections():
    """does not retain full reference-image data URLs in tracking collections"""
    pass


@pytest.mark.asyncio
async def test_persists_non_png_reference_images_with_their_own_extension(tmp_path):
    """persists non-PNG reference images with their own extension"""
    exporter = ReportImageExporter(
        str(tmp_path / "index.html"), str(tmp_path / "screenshots")
    )
    ref = {
        "type": "midscene_image_url_ref",
        "id": "svg-reference",
        "mimeType": "image/svg+xml",
        "storage": "inline",
    }

    name = exporter.write(ref, "data:image/svg+xml;base64,PHN2Zy8+")

    assert re.match(r"^[a-f0-9]{64}\.svg$", name)
    path = tmp_path / "screenshots" / name
    assert path.exists() is True
    assert path.read_bytes() == b"<svg/>"
    assert (
        "data:image/svg+xml;base64,"
        + base64.b64encode(path.read_bytes()).decode("ascii")
        == "data:image/svg+xml;base64,PHN2Zy8+"
    )


@pytest.mark.asyncio
async def test_rejects_malformed_reference_image_data_urls():
    """rejects malformed reference image data URLs"""
    with pytest.raises(
        ValueError, match="reference image must be a valid base64 image data URL"
    ):
        parse_base64_image_data_url("data:image/png,not-base64")


def test_rejects_unsafe_serialized_reference_image_file_names():
    """rejects unsafe serialized reference-image file names"""
    assert (
        normalize_image_url_ref(
            {
                "type": "midscene_image_url_ref",
                "id": "../outside",
                "mimeType": "image/webp",
                "storage": "inline",
            }
        )
        is None
    )


@pytest.mark.asyncio
async def test_supports_inline_mode_persistence_lazy_restore(tmp_path):
    """supports inline mode persistence + lazy restore"""
    report_path = tmp_path / "inline.html"
    appended = []

    def append_inline(image_id, image_base64):
        appended.append((image_id, image_base64))
        report_path.write_text(
            f'<script type="midscene-image" data-id="{image_id}">{image_base64}</script>',
            encoding="utf-8",
        )

    item = ScreenshotItem.create(PNG_BASE64, 100)
    append_inline(item.id, PNG_BASE64)
    item.mark_persisted_inline(str(report_path))

    assert item.has_base64() is False
    assert len(appended) == 1
    assert item.base64 == PNG_BASE64


@pytest.mark.skip(
    reason="Python ScreenshotItem cannot represent inline storage plus a shared "
    "file copy; ensureFileCopy/alsoWriteFileCopy is not ported"
)
@pytest.mark.asyncio
async def test_can_ensure_shared_file_copy_while_preserving_inline_mode_semantics():
    """can ensure shared file copy while preserving inline mode semantics"""
    pass


@pytest.mark.skip(reason="Python has no deprecated ensureFileCopy alias")
@pytest.mark.asyncio
async def test_keeps_supporting_ensurefilecopy_as_a_deprecated_alias():
    """keeps supporting ensureFileCopy as a deprecated alias"""
    pass


@pytest.mark.skip(
    reason="Python normalizes invalid screenshot references to None instead of "
    "raising 'invalid screenshot reference' from a store loader"
)
def test_throws_on_non_screenshotref_inputs():
    """throws on non-ScreenshotRef inputs"""
    pass
