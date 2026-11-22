"""Synced from upstream packages/core/tests/unit-test/html-utils.test.ts."""

from pathlib import Path

import pytest

from midscene.core.dump.html_utils import (
    collect_image_script_ids,
    extract_last_dump_script_sync,
    generate_agent_report_comment,
    generate_image_script_tag,
    stream_image_scripts_to_file,
    stream_scan_tags,
    stream_scan_tags_async,
)
from midscene.core.dump.screenshot_store import extract_image_by_id_sync

_INLINE_IMAGE_001 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_INLINE_IMAGE_002 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mNk"
    "+M9QzwAEjDAGAAcaBQGEcGp/AAAAAElFTkSuQmCC"
)
_INLINE_IMAGE_003 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAMAAAADCAYAAABWKLW/AAAAFElEQVR42mNk"
    "+M9Qz8DAwMDIAAUADmQBgYBhV6EAAAAASUVORK5CYII="
)


def _write_inline_sample(tmp_path):
    html_path = tmp_path / "inline-sample.html"
    html_path.write_text(
        "<!doctype html>\n<html>\n<head><title>Test Report</title></head>\n<body>\n"
        f'<script type="midscene-image" data-id="test-id-001">{_INLINE_IMAGE_001}</script>\n'
        f'<script type="midscene-image" data-id="test-id-002">{_INLINE_IMAGE_002}</script>\n'
        f'<script type="midscene-image" data-id="test-id-003">{_INLINE_IMAGE_003}</script>\n'
        '<script type="midscene_web_dump">{"groupName":"test","executions":[]}</script>\n'
        "</body>\n</html>\n",
        encoding="utf-8",
    )
    return html_path


@pytest.mark.asyncio
async def test_preserves_utf8_content_across_streaming_chunk_boundaries(tmp_path):
    """preserves UTF-8 content across streaming chunk boundaries"""
    file = tmp_path / "streaming.html"
    content = "报告🧪" * 30000
    file.write_text(f"<entry>{content}</entry>", encoding="utf-8")

    sync = []
    async_values = []
    stream_scan_tags(
        str(file), "<entry>", "</entry>", lambda value: sync.append(value) or False
    )
    await stream_scan_tags_async(
        str(file),
        "<entry>",
        "</entry>",
        lambda value: async_values.append(value) or False,
    )

    assert sync == [content]
    assert async_values == [content]


def test_keeps_report_bundled_sources_free_of_raw_script_close_tokens():
    """keeps report-bundled sources free of raw script close tokens"""
    # Upstream inspects its TypeScript bundle inputs. Python is not bundled by
    # that toolchain and legitimately contains the token in generated output.
    pytest.skip(
        reason="upstream check targets TypeScript bundle sources; the Python "
        "sources are not bundled with a raw script close token hazard"
    )


def test_generates_a_compact_agent_analysis_comment_for_report_html():
    """generates a compact agent analysis comment for report HTML"""
    comment = generate_agent_report_comment(
        {
            "sdkVersion": "1.0.0",
            "groupName": "checkout -- flow",
            "modelBriefs": [
                {
                    "intent": "planning",
                    "name": "gpt-4o",
                    "modelDescription": "vision planner",
                }
            ],
            "executions": [
                {
                    "logTime": 1710000000000,
                    "name": "exec",
                    "tasks": [
                        {
                            "taskId": "task-1",
                            "type": "Action Space",
                            "subType": "Tap",
                            "status": "finished",
                        }
                    ],
                }
            ],
        }
    )

    assert "For Agent Analysis" in comment
    assert 'script[type="midscene_web_dump"]' in comment
    assert 'script[type="midscene-image"]' in comment
    assert "planning: gpt-4o (vision planner)" in comment
    assert "checkout - - flow" in comment
    assert "checkout -- flow" not in comment


def test_falls_back_agent_comment_model_info_to_task_usage():
    """falls back agent comment model info to task usage"""
    comment = generate_agent_report_comment(
        {
            "sdkVersion": "1.0.0",
            "groupName": "usage model report",
            "modelBriefs": [],
            "executions": [
                {
                    "logTime": 1710000000000,
                    "name": "exec",
                    "tasks": [
                        {
                            "taskId": "task-1",
                            "type": "Planning",
                            "subType": "Plan",
                            "status": "finished",
                            "usage": {
                                "intent": "planning",
                                "model_name": "openai_qwen3.5-plus",
                                "model_description": "qwen3.5 mode",
                            },
                        }
                    ],
                }
            ],
        }
    )

    assert "Models: planning: openai_qwen3.5-plus (qwen3.5 mode)" in comment
    assert "No report-level model metadata recorded" not in comment


def test_keeps_agent_analysis_comments_optional_for_incomplete_execution_dumps():
    """keeps agent analysis comments optional for incomplete execution dumps"""
    comment = generate_agent_report_comment(
        {
            "sdkVersion": "1.0.0",
            "groupName": "incomplete report",
            "modelBriefs": [],
            "executions": [{"logTime": 1710000000000, "name": "exec"}],
        }
    )

    assert "Executions: 1; Tasks: 0" in comment
    assert "Models: No model metadata recorded" in comment


def test_should_extract_image_by_id_from_html_file(tmp_path):
    """should extract image by id from HTML file"""
    result = extract_image_by_id_sync(str(_write_inline_sample(tmp_path)), "test-id-001")

    assert result == _INLINE_IMAGE_001


def test_should_extract_different_images_by_their_ids(tmp_path):
    """should extract different images by their ids"""
    html_path = str(_write_inline_sample(tmp_path))
    result1 = extract_image_by_id_sync(html_path, "test-id-001")
    result2 = extract_image_by_id_sync(html_path, "test-id-002")
    result3 = extract_image_by_id_sync(html_path, "test-id-003")

    assert "iVBORw0KGgoAAAANSUhEUgAAAAE" in result1
    assert "iVBORw0KGgoAAAANSUhEUgAAAAI" in result2
    assert "iVBORw0KGgoAAAANSUhEUgAAAAM" in result3

    assert result1 != result2
    assert result2 != result3


def test_should_return_null_for_non_existent_id(tmp_path):
    """should return null for non-existent id"""
    result = extract_image_by_id_sync(
        str(_write_inline_sample(tmp_path)), "non-existent-id"
    )

    assert result is None


def test_should_throw_for_non_existent_file(tmp_path):
    """should throw for non-existent file"""
    with pytest.raises(FileNotFoundError):
        extract_image_by_id_sync(str(tmp_path / "non-existent-file.html"), "test-id-001")


_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_INLINE_REPORT = (
    _REPO_ROOT
    / "web-integration/midscene_run/report/puppeteer-2026-02-03_10-38-58-f3167a8e.html"
)
_REAL_FOLDER_REPORT = (
    _REPO_ROOT
    / "web-integration/midscene_run/report/puppeteer-2026-02-03_10-39-07-1afa62d2"
)


@pytest.mark.skipif(
    not _REAL_INLINE_REPORT.exists(), reason="real inline report fixture not present"
)
def test_should_extract_image_from_real_inline_report():
    """should extract image from real inline report"""
    image_id = "f30c01ea-1f97-49e8-8a34-ac7972044ce3"
    result = extract_image_by_id_sync(str(_REAL_INLINE_REPORT), image_id)

    assert result is not None
    assert "data:image/" in result
    assert "base64," in result


@pytest.mark.skipif(
    not _REAL_FOLDER_REPORT.exists(), reason="real folder report fixture not present"
)
def test_should_work_with_folder_report_html_no_inline_images():
    """should work with folder report HTML (no inline images)"""
    index_html = _REAL_FOLDER_REPORT / "index.html"
    result = extract_image_by_id_sync(
        str(index_html), "50a74f81-6750-4a9b-a11b-7842ae1b897b"
    )

    assert result is None


@pytest.mark.skipif(
    not _REAL_FOLDER_REPORT.exists(), reason="real folder report fixture not present"
)
def test_should_verify_screenshot_files_exist_in_folder_report():
    """should verify screenshot files exist in folder report"""
    image_file = (
        _REAL_FOLDER_REPORT
        / "screenshots"
        / "50a74f81-6750-4a9b-a11b-7842ae1b897b.png"
    )
    assert image_file.exists() is True

    buffer = image_file.read_bytes()
    assert len(buffer) > 0

    is_png = (
        buffer[0] == 0x89
        and buffer[1] == 0x50
        and buffer[2] == 0x4E
        and buffer[3] == 0x47
    )
    is_jpeg = buffer[0] == 0xFF and buffer[1] == 0xD8

    assert is_png or is_jpeg


def test_should_extract_dump_script_content_from_html_file(tmp_path):
    """should extract dump script content from HTML file"""
    result = extract_last_dump_script_sync(
        str(_write_inline_sample(tmp_path))
    )
    assert result == '{"groupName":"test","executions":[]}'


def test_should_extract_content_from_large_html_file(tmp_path):
    """should extract content from large HTML file"""
    huge_content = "a" * (3 * 1024 * 1024 - 200)
    large_html_path = tmp_path / "large.html"
    large_html_path.write_text(
        "<!DOCTYPE html>\n<html>\n<head><title>Test</title></head>\n<body>\n"
        f"{huge_content}\n"
        '<script type="midscene_web_dump" type="application/json">\n'
        "test\n"
        "</script>\n"
        "</body>\n</html>\n",
        encoding="utf-8",
    )
    assert extract_last_dump_script_sync(str(large_html_path)) == "test"


def test_should_extract_the_last_dump_script_when_multiple_exist(tmp_path):
    """should extract the LAST dump script when multiple exist"""
    html_path = tmp_path / "multiple.html"
    html_path.write_text(
        "<!DOCTYPE html>\n<html>\n<body>\n"
        '<script type="midscene_web_dump">first</script>\n'
        '<script type="midscene_web_dump">second</script>\n'
        '<script type="midscene_web_dump">last</script>\n'
        "</body>\n</html>\n",
        encoding="utf-8",
    )
    assert extract_last_dump_script_sync(str(html_path)) == "last"


def test_should_return_empty_string_for_file_without_dump_script(tmp_path):
    """should return empty string for file without dump script"""
    html_path = tmp_path / "empty.html"
    html_path.write_text(
        "<html><body>no script</body></html>", encoding="utf-8"
    )
    assert extract_last_dump_script_sync(str(html_path)) == ""


@pytest.mark.asyncio
async def test_collects_inline_image_ids_asynchronously_across_streaming_chunks(
    tmp_path,
):
    """collects inline image IDs asynchronously across streaming chunks"""
    html_path = tmp_path / "images.html"
    chunk_boundary_padding = "x" * (64 * 1024 - 20)
    html_path.write_text(
        "\n".join(
            [
                chunk_boundary_padding,
                generate_image_script_tag(
                    "first-image", "data:image/png;base64,AAA"
                ),
                generate_image_script_tag(
                    "second-image", "data:image/png;base64,BBB"
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert await collect_image_script_ids(str(html_path)) == {
        "first-image",
        "second-image",
    }


def test_should_stream_image_scripts_from_source_to_destination(tmp_path):
    """should stream image scripts from source to destination"""
    src_path = tmp_path / "source.html"
    dest_path = tmp_path / "dest.html"
    image_tag1 = generate_image_script_tag("img-1", "data:image/png;base64,AAA")
    image_tag2 = generate_image_script_tag("img-2", "data:image/png;base64,BBB")
    src_path.write_text(
        "<!DOCTYPE html>\n<html>\n<body>\n"
        f"{image_tag1}\n"
        f"{image_tag2}\n"
        '<script type="midscene_web_dump">{"test":true}</script>\n'
        "</body>\n</html>\n",
        encoding="utf-8",
    )
    dest_path.write_text("", encoding="utf-8")

    stream_image_scripts_to_file(str(src_path), str(dest_path))

    dest_content = dest_path.read_text(encoding="utf-8")
    assert 'data-id="img-1"' in dest_content
    assert 'data-id="img-2"' in dest_content
    assert "AAA" in dest_content
    assert "BBB" in dest_content


def test_should_deduplicate_image_ids_across_streamed_reports(tmp_path):
    """should deduplicate image IDs across streamed reports"""
    first_src_path = tmp_path / "first.html"
    second_src_path = tmp_path / "second.html"
    dest_path = tmp_path / "dest.html"
    shared_image = generate_image_script_tag(
        "shared-image", "data:image/png;base64,AAA"
    )
    unique_image = generate_image_script_tag(
        "unique-image", "data:image/png;base64,BBB"
    )
    first_src_path.write_text(shared_image, encoding="utf-8")
    second_src_path.write_text(
        f"{shared_image}\n{unique_image}", encoding="utf-8"
    )
    dest_path.write_text("", encoding="utf-8")

    written_image_ids = set()
    stream_image_scripts_to_file(
        str(first_src_path), str(dest_path), written_image_ids
    )
    stream_image_scripts_to_file(
        str(second_src_path), str(dest_path), written_image_ids
    )

    dest_content = dest_path.read_text(encoding="utf-8")
    assert len(dest_content.split('data-id="shared-image"')) == 2
    assert len(dest_content.split('data-id="unique-image"')) == 2
    assert written_image_ids == {"shared-image", "unique-image"}


def test_should_handle_file_with_no_image_scripts(tmp_path):
    """should handle file with no image scripts"""
    src_path = tmp_path / "source.html"
    dest_path = tmp_path / "dest.html"
    src_path.write_text(
        "<html><body>no images</body></html>", encoding="utf-8"
    )
    dest_path.write_text("", encoding="utf-8")

    stream_image_scripts_to_file(str(src_path), str(dest_path))

    assert dest_path.read_text(encoding="utf-8") == ""
