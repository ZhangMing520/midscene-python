"""Synced from upstream packages/core/tests/unit-test/screenshot-store.test.ts."""

import json
import re

import pytest

from midscene.core.dump.report_action_dump import ExecutionDump, ReportActionDump
from midscene.core.dump.screenshot_store import (
    ReportImageStore,
    normalize_image_url_ref,
)
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
    store = ReportImageStore("directory", report_path, screenshots_dir)

    ref = store.persist(item)

    assert item.has_base64() is False
    assert ref["storage"] == "file"
    assert (tmp_path / store.get_file_path(item.id)).exists() is True
    assert "data:image/png;base64," in store.load_base64(ref)


@pytest.mark.asyncio
async def test_shares_bytes_across_observations_and_reference_images_while_keeping_observation_identity(
    tmp_path,
):
    """shares bytes across observations and reference images while keeping observation identity"""
    store = ReportImageStore(
        "directory",
        tmp_path / "index.html",
        tmp_path / "screenshots",
    )
    first = ScreenshotItem.create(PNG_BASE64, 100)
    second = ScreenshotItem.create(PNG_BASE64, 200)

    first_ref = store.persist(first)
    second_ref = store.persist(second)
    reference = store.persist_reference_image(PNG_BASE64)

    assert first_ref["id"] != second_ref["id"]
    assert [first_ref["capturedAt"], second_ref["capturedAt"]] == [100, 200]
    assert first_ref["path"] == second_ref["path"]
    assert first_ref["path"] == reference["path"]
    assert re.match(r"^\./screenshots/[a-f0-9]{64}\.png$", first_ref["path"])
    assert len(list((tmp_path / "screenshots").iterdir())) == 1
    assert first.base64 == PNG_BASE64
    assert second.base64 == PNG_BASE64


@pytest.mark.asyncio
async def test_round_trips_screenshots_through_dump_companion_files(tmp_path):
    """round-trips screenshots through dump companion files"""
    dump_path = tmp_path / "execution.json"
    screenshot = ScreenshotItem.create(PNG_BASE64, 100)
    execution = ExecutionDump(
        {
            "id": "execution-with-file-screenshot",
            "logTime": 100,
            "name": "execution-with-file-screenshot",
            "tasks": [
                {
                    "taskId": "task-with-file-screenshot",
                    "type": "Insight",
                    "subType": "Locate",
                    "param": {},
                    "uiContext": {
                        "screenshot": screenshot,
                        "shotSize": {"width": 5, "height": 5},
                        "shrunkShotToLogicalRatio": 1,
                    },
                    "recorder": [],
                    "status": "finished",
                }
            ],
        }
    )
    dump = ReportActionDump(
        {
            "sdkVersion": "1.0.0-test",
            "groupName": "companion-file-round-trip",
            "modelBriefs": [],
            "executions": [execution],
        }
    )

    dump.serialize_to_files(str(dump_path))
    restored = json.loads(ReportActionDump.from_files_as_inline_json(str(dump_path)))

    assert (
        restored["executions"][0]["tasks"][0]["uiContext"]["screenshot"]["base64"]
        == PNG_BASE64
    )


@pytest.mark.asyncio
async def test_deduplicates_same_screenshot_persistence_by_id(tmp_path):
    """deduplicates same screenshot persistence by id"""
    store = ReportImageStore(
        "directory",
        tmp_path / "index.html",
        tmp_path / "screenshots",
    )
    item = ScreenshotItem.create(PNG_BASE64, 100)

    first = store.persist(item)
    (tmp_path / store.get_file_path(item.id)).write_text("marker", encoding="utf-8")
    second = store.persist(item)

    assert first["id"] == second["id"]
    assert (tmp_path / store.get_file_path(item.id)).read_text(
        encoding="utf-8"
    ) == "marker"


@pytest.mark.asyncio
async def test_deduplicates_inline_reference_images_by_content(tmp_path):
    """deduplicates inline reference images by content"""
    report_path = tmp_path / "reference-inline.html"
    appended = []
    store = ReportImageStore(
        "inline",
        report_path,
        write_inline_image=lambda image_id, image: appended.append((image_id, image)),
    )
    reference_image = "data:image/webp;base64,QUJDRA=="

    first = store.persist_reference_image(reference_image)
    repeated = store.persist_reference_image(reference_image)
    second = store.persist_reference_image(
        "data:image/webp;name=reference;base64,QUJD RA=="
    )

    assert first["type"] == "midscene_image_url_ref"
    assert first["mimeType"] == "image/webp"
    assert first["storage"] == "inline"
    assert repeated == first
    assert second["id"] == first["id"]
    assert len(appended) == 1
    assert appended[0] == (first["id"], reference_image)


@pytest.mark.asyncio
async def test_does_not_retain_full_reference_image_data_urls_in_tracking_collections(
    tmp_path,
):
    """does not retain full reference-image data URLs in tracking collections"""
    store = ReportImageStore(
        "inline",
        tmp_path / "bounded-reference-tracking.html",
        write_inline_image=lambda _image_id, _image: None,
    )

    for marker in ["QUJDRA==", "RUZHSA==", "SUpLTA=="]:
        store.persist_reference_image(f"data:image/webp;base64,{marker}")

    tracked_values = []
    for value in store.__dict__.values():
        if isinstance(value, dict):
            tracked_values.extend(value.keys())
            tracked_values.extend(value.values())
        elif isinstance(value, (set, list, tuple)):
            tracked_values.extend(value)

    assert not any(
        isinstance(value, str) and value.startswith("data:image/")
        for value in tracked_values
    )


@pytest.mark.asyncio
async def test_persists_non_png_reference_images_with_their_own_extension(
    tmp_path,
):
    """persists non-PNG reference images with their own extension"""
    report_path = tmp_path / "index.html"
    screenshots_dir = tmp_path / "screenshots"
    store = ReportImageStore("directory", report_path, screenshots_dir)

    ref = store.persist_reference_image("data:image/svg+xml;base64,PHN2Zy8+")

    assert re.match(r"^\./screenshots/[a-f0-9]{64}\.svg$", ref["path"])
    assert (tmp_path / ref["path"]).exists() is True
    assert store.load_data_uri(ref) == "data:image/svg+xml;base64,PHN2Zy8+"


@pytest.mark.asyncio
async def test_rejects_malformed_reference_image_data_urls(tmp_path):
    """rejects malformed reference image data URLs"""
    store = ReportImageStore(
        "inline",
        tmp_path / "invalid-reference.html",
        write_inline_image=lambda _image_id, _image: None,
    )

    with pytest.raises(
        ValueError, match="reference image must be a valid base64 image data URL"
    ):
        store.persist_reference_image("data:image/png,not-base64")


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
            f'<script type="midscene-image" data-id="{image_id}">'
            f"{image_base64}</script>",
            encoding="utf-8",
        )

    store = ReportImageStore("inline", report_path, write_inline_image=append_inline)
    item = ScreenshotItem.create(PNG_BASE64, 100)

    ref = store.persist(item)

    assert item.has_base64() is False
    assert len(appended) == 1
    assert store.load_base64(ref) == PNG_BASE64


@pytest.mark.asyncio
async def test_can_ensure_shared_file_copy_while_preserving_inline_mode_semantics(
    tmp_path,
):
    """can ensure shared file copy while preserving inline mode semantics"""
    report_path = tmp_path / "inline-with-file-copy.html"
    screenshots_dir = tmp_path / "screenshots"
    appended = []

    def append_inline(image_id, image_base64):
        appended.append((image_id, image_base64))
        report_path.write_text(
            f'<script type="midscene-image" data-id="{image_id}">'
            f"{image_base64}</script>",
            encoding="utf-8",
        )

    store = ReportImageStore(
        "inline",
        report_path,
        screenshots_dir,
        write_inline_image=append_inline,
        also_write_file_copy=True,
    )
    item = ScreenshotItem.create(PNG_BASE64, 100)

    ref = store.persist(item)

    assert ref["storage"] == "inline"
    assert item.to_serializable()["storage"] == "inline"
    assert len(appended) == 1
    assert (tmp_path / store.get_file_path(item.id)).exists() is True
    (tmp_path / store.get_file_path(item.id)).unlink()
    assert item.base64 == PNG_BASE64
    assert store.load_base64(ref) == PNG_BASE64


@pytest.mark.asyncio
async def test_keeps_supporting_ensurefilecopy_as_a_deprecated_alias(tmp_path):
    """keeps supporting ensureFileCopy as a deprecated alias"""
    report_path = tmp_path / "inline-with-deprecated-file-copy.html"
    screenshots_dir = tmp_path / "screenshots"

    def append_inline(image_id, image_base64):
        report_path.write_text(
            f'<script type="midscene-image" data-id="{image_id}">'
            f"{image_base64}</script>",
            encoding="utf-8",
        )

    store = ReportImageStore(
        "inline",
        report_path,
        screenshots_dir,
        write_inline_image=append_inline,
        ensure_file_copy=True,
    )
    item = ScreenshotItem.create(PNG_BASE64, 100)

    ref = store.persist(item)

    assert ref["storage"] == "inline"
    assert (tmp_path / store.get_file_path(item.id)).exists() is True


def test_throws_on_non_screenshotref_inputs(tmp_path):
    """throws on non-ScreenshotRef inputs"""
    store = ReportImageStore(
        "inline",
        tmp_path / "invalid-ref.html",
        write_inline_image=lambda _image_id, _image: None,
    )

    with pytest.raises(ValueError, match="invalid screenshot reference"):
        store.load_base64({"$screenshot": "legacy-id", "capturedAt": 1})
    with pytest.raises(ValueError, match="invalid screenshot reference"):
        store.load_base64({"base64": "./screenshots/legacy.png", "capturedAt": 1})
