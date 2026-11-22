"""Synced from upstream packages/core/tests/unit-test/report-generator-directory.test.ts.

The Python ReportGenerator (midscene.core.report_generator) only renders a
single self-contained HTML file: it has no ``screenshotMode: 'directory'``,
``reuseExistingReport`` or ``persistExecutionDump`` streaming writer. Every
upstream case in this file therefore depends on directory-mode behavior that
the Python port does not implement.
"""

import pytest

_SKIP = pytest.mark.skip(
    reason="Python ReportGenerator has no screenshotMode='directory' writer, "
    "so directory artifacts, asset typing and shared-writer finalization "
    "cannot be exercised"
)


@_SKIP
@pytest.mark.asyncio
async def test_preserves_the_same_facts_and_images_in_standalone_html_and_directory_reports():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_preserves_explicit_constructor_entry_names_and_fails_loudly_for_incompatible_reuse():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_preserves_exact_screenshot_pixels_in_portable_external_assets():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_writes_typed_png_jpeg_assets_once_and_releases_recoverable_screenshot_memory():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_replaces_progress_facts_preserves_independent_observations_and_publishes_attributes():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_retains_all_execution_ids_and_reused_agent_groups_for_report_tools():
    pass


@_SKIP
@pytest.mark.asyncio
async def test_completes_a_shared_report_only_after_all_published_writers_finalize():
    pass
