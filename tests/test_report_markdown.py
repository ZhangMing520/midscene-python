"""Synced from upstream packages/core/tests/unit-test/report-markdown.test.ts.

Upstream exposes ``executionToMarkdown`` / ``reportToMarkdown`` returning
``{markdown, attachments}`` with screenshot file links, model info, timing and
token summaries. The Python port only has ``report_to_markdown`` (a plain
string with a different layout) and no ``execution_to_markdown``, so every
upstream case is kept and skipped with a concrete reason.
"""

import pytest

_NO_API_SKIP = pytest.mark.skip(
    reason="Python has no executionToMarkdown port; report_to_markdown returns "
    "a plain string without attachments or screenshot links"
)


@_NO_API_SKIP
def test_handles_single_execution_markdown_with_screenshot_file_links():
    """handles single execution markdown with screenshot file links"""
    pass


@_NO_API_SKIP
def test_merges_all_executions_into_one_markdown_and_keeps_file_snapshot():
    """merges all executions into one markdown and keeps file snapshot"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown has no screenshotBaseDir option and does "
    "not render callAiStart/callAiEnd timing fallbacks"
)
def test_uses_timing_fallback_fields_and_custom_screenshot_directory():
    """uses timing fallback fields and custom screenshot directory"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown returns no attachments and does not "
    "preserve restored screenshot sourceRef metadata"
)
def test_preserves_restored_screenshot_source_refs_for_file_backed_export():
    """preserves restored screenshot source refs for file-backed export"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown renders no Model Info, Timing Summary or "
    "Token Usage Summary sections and no per-task usage/thought blocks"
)
def test_includes_model_metadata_token_usage_and_task_context_for_agent_analysis():
    """includes model metadata, token usage, and task context for agent analysis"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown has no wallTimeFallbackMs option or "
    "elapsed-time fallback explanation"
)
def test_explains_the_elapsed_time_fallback_in_markdown():
    """explains the elapsed-time fallback in markdown"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown has no Model Info section to fall back to "
    "task usage"
)
def test_falls_back_report_model_info_to_task_usage_when_model_briefs_are_missing():
    """falls back report model info to task usage when model briefs are missing"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown has no recorder screenshot attachment "
    "extraction for base64 strings or file references"
)
def test_handles_recorder_screenshots_stored_as_base64_strings():
    """handles recorder screenshots stored as base64 strings"""
    pass


@pytest.mark.skip(
    reason="Python has no executionToMarkdown input validation and "
    "report_to_markdown does not raise for a missing executions array"
)
def test_throws_with_invalid_input():
    """throws with invalid input"""
    pass


@pytest.mark.skip(
    reason="Python report_to_markdown renders task state headings but no "
    "'Screen size: N/A' line, so the upstream no-screenshot assertions differ"
)
def test_gracefully_skips_tasks_without_screenshots():
    """gracefully skips tasks without screenshots"""
    pass
