"""Synced from upstream packages/core/tests/unit-test/report-generator-directory.test.ts."""

import asyncio
import base64
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

import pytest
from PIL import Image

from midscene.core.dump.report_artifact_reader import (
    read_report_artifact_manifest,
    read_report_dump_scripts,
)
from midscene.core.dump.screenshot_restoration import (
    RestoredScreenshotReference,
    restore_image_references,
)
from midscene.core.dump.screenshot_store import (
    ReportImageStore,
    resolve_image_source,
)
from midscene.core.report import (
    collect_deduped_executions,
    is_directory_mode_report,
)
from midscene.core.report_generator import ReportGenerator
from midscene.core.screenshot_item import ScreenshotItem

DEFAULT_REPORT_META = {
    "groupName": "test-group",
    "groupDescription": "test",
    "sdkVersion": "1.0.0-test",
    "modelBriefs": [],
}

_execution_counter = 0


def _fake_base64(size_bytes: int, image_format: str = "png") -> str:
    """Create a valid-looking image data URL with a predictable payload size."""
    return f"data:image/{image_format};base64," + "A" * size_bytes


def _create_execution(
    screenshots,
    name: str = "test-execution",
    execution_id: str = None,
):
    global _execution_counter
    _execution_counter += 1
    tasks = [
        {
            "taskId": f"task-{index}",
            "type": "Insight",
            "subType": "Locate",
            "param": {"prompt": f"task-{index}"},
            "uiContext": {
                "screenshot": screenshot,
                "shotSize": {"width": 1920, "height": 1080},
                "shrunkShotToLogicalRatio": 1,
            },
            "recorder": [],
            "status": "running",
        }
        for index, screenshot in enumerate(screenshots)
    ]
    return {
        "id": execution_id or f"exec-id-{_execution_counter}",
        "logTime": int(time.time() * 1000),
        "name": name,
        "tasks": tasks,
    }


def _generator_at(path, reuse_existing_report: bool = False) -> ReportGenerator:
    return ReportGenerator(
        report_path=str(path),
        screenshot_mode="directory",
        auto_print=False,
        reuse_existing_report=reuse_existing_report,
    )


def _parse_script_attributes(open_tag: str):
    attributes = {}
    for match in re.finditer(r'([^\s=]+)="([^"]*)"', open_tag):
        attributes[match.group(1)] = unquote(match.group(2))
    return attributes


def _decode_image_pixels(image: bytes):
    with Image.open(io.BytesIO(image)) as decoded:
        rgb = decoded.convert("RGB")
        return {
            "width": rgb.width,
            "height": rgb.height,
            "pixels": list(rgb.getdata()),
        }


def _create_patterned_png_fixture():
    pixels = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    image = Image.new("RGB", (2, 2))
    image.putdata(pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return (
        "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        {"width": 2, "height": 2, "pixels": pixels},
    )


def _screenshot_file_path(report_directory: Path, screenshot: ScreenshotItem) -> str:
    """Find an asset by bytes, without coupling tests to its naming algorithm."""
    expected = base64.b64decode(screenshot.raw_base64)
    directory = Path(report_directory) / "screenshots"
    for name in os.listdir(directory):
        candidate = directory / name
        if candidate.read_bytes() == expected:
            return str(candidate)
    raise AssertionError(f"Missing screenshot asset for {screenshot.id}")


def _plain(value):
    """Resolve lazy image references and drop the internal source ref."""
    if isinstance(value, RestoredScreenshotReference):
        value = value.to_dict()
    if isinstance(value, dict):
        return {
            key: _plain(item)
            for key, item in value.items()
            if key != "sourceRef"
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_preserves_the_same_facts_and_images_in_standalone_html_and_directory_reports(
    tmp_path,
):
    screenshot = ScreenshotItem.create(_fake_base64(100), 100)
    execution = _create_execution([screenshot], "failed login", "login")
    execution["tasks"][0]["status"] = "failed"
    execution["tasks"][0]["errorMessage"] = "Login button is missing"
    meta = {**DEFAULT_REPORT_META, "modelBriefs": [{"name": "test-model"}]}

    restored = []
    for mode in ("inline", "directory"):
        path = (
            tmp_path / "single.html"
            if mode == "inline"
            else tmp_path / "external" / "index.html"
        )
        generator = ReportGenerator(
            report_path=str(path),
            screenshot_mode=mode,
            auto_print=False,
        )
        generator.on_execution_update(execution, meta)
        await generator.finalize()
        store = ReportImageStore(mode=mode, report_path=str(path))
        dump = json.loads(read_report_dump_scripts(path)[0]["content"])
        restored.append(
            _plain(restore_image_references(dump, store.load_data_uri))
        )

    assert restored[0] == restored[1]
    assert "Login button is missing" in json.dumps(restored[0])
    assert "test-model" in json.dumps(restored[0])
    assert (tmp_path / "screenshots").exists() is False


@pytest.mark.asyncio
async def test_preserves_explicit_constructor_entry_names_and_fails_loudly_for_incompatible_reuse(
    tmp_path,
):
    path = tmp_path / "custom.html"
    generator = _generator_at(path)
    generator.on_execution_update(_create_execution([]), DEFAULT_REPORT_META)
    await generator.finalize()
    assert read_report_artifact_manifest(str(path))["entry"] == "custom.html"
    assert is_directory_mode_report(str(path)) is True
    _generator_at(path, True)  # Compatible reuse must not throw.

    inline_path = tmp_path / "inline.html"
    inline = ReportGenerator(
        report_path=str(inline_path),
        screenshot_mode="inline",
        auto_print=False,
    )
    inline.on_execution_update(_create_execution([]), DEFAULT_REPORT_META)
    await inline.finalize()
    with pytest.raises(ValueError, match="incompatible directory report"):
        _generator_at(inline_path, True)


@pytest.mark.asyncio
async def test_preserves_exact_screenshot_pixels_in_portable_external_assets(
    tmp_path,
):
    report_path = tmp_path / "pixels" / "index.html"
    generator = _generator_at(report_path)
    data_uri, expected_image = _create_patterned_png_fixture()
    screenshot = ScreenshotItem.create(data_uri, 100)
    generator.on_execution_update(
        _create_execution([screenshot]), DEFAULT_REPORT_META
    )
    await generator.finalize()

    assert (
        _decode_image_pixels(
            Path(
                _screenshot_file_path(report_path.parent, screenshot)
            ).read_bytes()
        )
        == expected_image
    )
    assert data_uri not in report_path.read_text(encoding="utf-8")
    assert read_report_artifact_manifest(str(report_path))["status"] == "complete"
    assert sorted(os.listdir(report_path.parent)) == [
        "data",
        "index.html",
        "report.json",
        "screenshots",
    ]

    moved_dir = tmp_path / "moved"
    report_path.parent.rename(moved_dir)
    moved = moved_dir / "index.html"
    dump = json.loads(read_report_dump_scripts(moved)[0]["content"])
    resolved = resolve_image_source(
        dump["executions"][0]["tasks"][0]["uiContext"]["screenshot"],
        {"reportPath": str(moved)},
    )
    assert resolved["type"] == "file"
    assert _decode_image_pixels(Path(resolved["filePath"]).read_bytes()) == (
        expected_image
    )


@pytest.mark.asyncio
async def test_writes_typed_png_jpeg_assets_once_and_releases_recoverable_screenshot_memory(
    tmp_path,
):
    path = tmp_path / "typed" / "index.html"
    generator = _generator_at(path)
    png = ScreenshotItem.create(_fake_base64(500), 100)
    jpeg = ScreenshotItem.create(_fake_base64(500, "jpeg"), 200)
    execution = _create_execution([png, jpeg])
    generator.on_execution_update(execution, DEFAULT_REPORT_META)
    await generator.flush()

    png_path = _screenshot_file_path(path.parent, png)
    mtime = os.stat(png_path).st_mtime_ns
    generator.on_execution_update(execution, DEFAULT_REPORT_META)
    await generator.finalize()

    assert os.stat(png_path).st_mtime_ns == mtime
    assert png.has_base64() is False
    assert png.base64 == _fake_base64(500)

    dump = json.loads(read_report_dump_scripts(path)[0]["content"])
    for index, item in enumerate([png, jpeg]):
        ref = dump["executions"][0]["tasks"][index]["uiContext"]["screenshot"]
        assert ref["type"] == "midscene_screenshot_ref"
        assert ref["id"] == item.id
        assert ref["capturedAt"] == item.captured_at
        assert ref["storage"] == "file"
        assert re.search(
            r"[a-f0-9]{64}\.png$" if index == 0 else r"[a-f0-9]{64}\.jpeg$",
            ref["path"],
        )
        assert (path.parent / ref["path"]).exists() is True


@pytest.mark.asyncio
async def test_replaces_progress_facts_preserves_independent_observations_and_publishes_attributes(
    tmp_path,
):
    path = tmp_path / "updates" / "index.html"
    generator = ReportGenerator(
        report_path=str(path),
        screenshot_mode="directory",
        persist_execution_dump=True,
        auto_print=False,
    )
    first = ScreenshotItem.create(_fake_base64(100), 100)
    second = ScreenshotItem.create(_fake_base64(100), 200)
    execution = _create_execution([first, second], "login", "login")
    generator.on_execution_update(
        execution, DEFAULT_REPORT_META, {"playwright_test_title": "first"}
    )
    await generator.flush()
    first_html = path.read_text(encoding="utf-8")
    data_path = read_report_artifact_manifest(str(path))["groups"][0]["dumps"][0]

    execution["name"] = "login finished"
    generator.on_execution_update(
        execution,
        DEFAULT_REPORT_META,
        {
            "playwright_test_title": "final",
            "playwright_test_duration": 456,
        },
    )
    await generator.finalize()

    assert path.read_text(encoding="utf-8") == first_html
    scripts = read_report_dump_scripts(path)
    assert len(scripts) == 1
    attributes = _parse_script_attributes(scripts[0]["openTag"])
    assert attributes["playwright_test_title"] == "final"
    assert attributes["playwright_test_duration"] == "456"
    assert (
        json.loads(scripts[0]["content"])["executions"][0]["name"]
        == "login finished"
    )
    assert read_report_artifact_manifest(str(path))["groups"][0]["dumps"] == [
        data_path
    ]
    assert len(os.listdir(path.parent / "screenshots")) == 1
    assert (
        any(
            name.endswith(".execution.json")
            for name in os.listdir(path.parent)
        )
        is False
    )
    assert first.id != second.id


@pytest.mark.asyncio
async def test_retains_all_execution_ids_and_reused_agent_groups_for_report_tools(
    tmp_path,
):
    path = tmp_path / "reuse" / "index.html"
    for stream in ("a", "b"):
        generator = _generator_at(path, True)
        for step in ("1", "2"):
            generator.on_execution_update(
                _create_execution([], "same name", f"{stream}-{step}"),
                DEFAULT_REPORT_META,
            )
        await generator.finalize()

    assert is_directory_mode_report(str(path)) is True
    assert len(read_report_artifact_manifest(str(path))["groups"]) == 2
    assert [
        execution["id"]
        for execution in collect_deduped_executions(str(path))["executions"]
    ] == ["a-1", "a-2", "b-1", "b-2"]


@pytest.mark.asyncio
async def test_completes_a_shared_report_only_after_all_published_writers_finalize(
    tmp_path,
):
    path = tmp_path / "shared" / "index.html"
    a = _generator_at(path, True)
    b = _generator_at(path, True)
    a.on_execution_update(_create_execution([], "a", "a"), DEFAULT_REPORT_META)
    b.on_execution_update(_create_execution([], "b", "b"), DEFAULT_REPORT_META)
    await asyncio.gather(a.flush(), b.flush())
    await a.finalize()

    manifest = read_report_artifact_manifest(str(path))
    assert manifest["status"] == "running"
    assert sorted(group["status"] for group in manifest["groups"]) == [
        "complete",
        "running",
    ]

    b.on_execution_update(
        _create_execution([], "b updated", "b"), DEFAULT_REPORT_META
    )
    await b.flush()
    assert read_report_artifact_manifest(str(path))["status"] == "running"

    await b.finalize()
    assert read_report_artifact_manifest(str(path))["status"] == "complete"

    # Repeated finalize must preserve the completed state.
    await asyncio.gather(a.finalize(), b.finalize())
    assert read_report_artifact_manifest(str(path))["status"] == "complete"
