"""Synced from upstream packages/core/tests/unit-test/html-utils.test.ts.

The Python port only writes self-contained HTML reports; upstream's Node
streaming scanners (streamScanTags / extractLastDumpScriptSync /
collectImageScriptIds / streamImageScriptsToFile) and the agent analysis
comment generator are not ported. Inline image extraction is available as
``extract_image_by_id_sync`` in ``midscene.core.dump.screenshot_store``.
"""

from pathlib import Path

import pytest

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


_STREAMING_SKIP = pytest.mark.skip(
    reason="Python html_utils has no Node streaming tag scanner "
    "(streamScanTags / streamScanTagsAsync)"
)
_COMMENT_SKIP = pytest.mark.skip(
    reason="Python html_utils has no generateAgentReportComment port"
)
_DUMP_SKIP = pytest.mark.skip(
    reason="Python html_utils has no extractLastDumpScriptSync port"
)


@_STREAMING_SKIP
@pytest.mark.asyncio
async def test_preserves_utf8_content_across_streaming_chunk_boundaries():
    """preserves UTF-8 content across streaming chunk boundaries"""
    pass


def test_keeps_report_bundled_sources_free_of_raw_script_close_tokens():
    """keeps report-bundled sources free of raw script close tokens"""
    # Upstream inspects its TypeScript bundle inputs. Python is not bundled by
    # that toolchain and legitimately contains the token in generated output.
    pytest.skip(
        reason="upstream check targets TypeScript bundle sources; the Python "
        "sources are not bundled with a raw script close token hazard"
    )


@_COMMENT_SKIP
def test_generates_a_compact_agent_analysis_comment_for_report_html():
    """generates a compact agent analysis comment for report HTML"""
    pass


@_COMMENT_SKIP
def test_falls_back_agent_comment_model_info_to_task_usage():
    """falls back agent comment model info to task usage"""
    pass


@_COMMENT_SKIP
def test_keeps_agent_analysis_comments_optional_for_incomplete_execution_dumps():
    """keeps agent analysis comments optional for incomplete execution dumps"""
    pass


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


@_DUMP_SKIP
def test_should_extract_dump_script_content_from_html_file(tmp_path):
    """should extract dump script content from HTML file"""
    pass


@_DUMP_SKIP
def test_should_extract_content_from_large_html_file(tmp_path):
    """should extract content from large HTML file"""
    pass


@_DUMP_SKIP
def test_should_extract_the_last_dump_script_when_multiple_exist(tmp_path):
    """should extract the LAST dump script when multiple exist"""
    pass


@_DUMP_SKIP
def test_should_return_empty_string_for_file_without_dump_script(tmp_path):
    """should return empty string for file without dump script"""
    pass


@_STREAMING_SKIP
@pytest.mark.asyncio
async def test_collects_inline_image_ids_asynchronously_across_streaming_chunks(tmp_path):
    """collects inline image IDs asynchronously across streaming chunks"""
    pass


@pytest.mark.skip(reason="Python html_utils has no streamImageScriptsToFile port")
def test_should_stream_image_scripts_from_source_to_destination(tmp_path):
    """should stream image scripts from source to destination"""
    pass


@pytest.mark.skip(reason="Python html_utils has no streamImageScriptsToFile port")
def test_should_deduplicate_image_ids_across_streamed_reports(tmp_path):
    """should deduplicate image IDs across streamed reports"""
    pass


@pytest.mark.skip(reason="Python html_utils has no streamImageScriptsToFile port")
def test_should_handle_file_with_no_image_scripts(tmp_path):
    """should handle file with no image scripts"""
    pass
