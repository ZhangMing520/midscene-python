"""Synced from upstream packages/core/tests/unit-test/report.test.ts.

The upstream suite drives ``ReportMergingTool`` (append / mergeReports /
clear), ``isDirectoryModeReport`` and the inline image/dump script helpers.
The Python port has no report merging tool or directory-mode merge pipeline,
so every upstream case is kept here and skipped with a concrete reason.
"""

import pytest

_MERGE_SKIP = pytest.mark.skip(
    reason="Python has no ReportMergingTool.append/mergeReports port "
    "(upstream core/src/report.ts), so report merging cannot be exercised"
)
_DIRECTORY_SKIP = pytest.mark.skip(
    reason="Python has no ReportMergingTool directory-mode merge "
    "(outputFormat='html-and-external-assets') or screenshot copying"
)
_DETECT_SKIP = pytest.mark.skip(
    reason="Python has no isDirectoryModeReport port to inspect the "
    "data-screenshot-mode metadata on a report"
)


@_MERGE_SKIP
def test_should_merge_3_mocked_reports():
    """should merge 3 mocked reports"""
    pass


@_MERGE_SKIP
def test_should_merge_3_mocked_reports_and_delete_original_reports_after_that():
    """should merge 3 mocked reports, and delete original reports after that."""
    pass


@_MERGE_SKIP
def test_should_merge_3_mocked_reports_use_user_custom_filename():
    """should merge 3 mocked reports, use user custom filename"""
    pass


@_MERGE_SKIP
def test_should_merge_3_mocked_reports_twice_use_user_custom_filename_overwrite_old_report_on_second_merge():
    """should merge 3 mocked reports twice, use user custom filename, overwrite old report on second merge"""
    pass


@_MERGE_SKIP
def test_should_merge_100_mocked_reports_and_delete_original_reports_after_that():
    """should merge 100 mocked reports, and delete original reports after that."""
    pass


@_DIRECTORY_SKIP
def test_should_merge_directory_mode_reports_and_copy_screenshots():
    """should merge directory mode reports and copy screenshots"""
    pass


@_DIRECTORY_SKIP
def test_should_delete_entire_directory_for_directory_mode_reports_when_rm_original_reports_is_true():
    """should delete entire directory for directory mode reports when rmOriginalReports is true"""
    pass


@_DETECT_SKIP
def test_detects_directory_mode_from_metadata_even_without_a_screenshots_dir():
    """detects directory mode from metadata even without a screenshots dir"""
    pass


@_DIRECTORY_SKIP
def test_removes_the_whole_directory_of_a_screenshot_less_directory_mode_report_on_rm_original_reports():
    """removes the whole directory of a screenshot-less directory mode report on rmOriginalReports"""
    pass


@_DIRECTORY_SKIP
def test_removes_the_folder_of_a_legacy_inline_screenshot_directory_report_on_rm_original_reports():
    """removes the folder of a legacy inline-screenshot directory report on rmOriginalReports"""
    pass


@_MERGE_SKIP
def test_should_merge_a_single_report():
    """should merge a single report"""
    pass


@_MERGE_SKIP
def test_should_handle_reports_with_undefined_report_file_path():
    """should handle reports with undefined reportFilePath (e.g. skipped tests)"""
    pass


@_MERGE_SKIP
def test_should_reject_a_missing_report_file_path_for_non_skipped_tests():
    """should reject a missing reportFilePath for non-skipped tests"""
    pass


@_MERGE_SKIP
def test_should_return_null_when_no_reports_are_appended():
    """should return null when no reports are appended"""
    pass


@_MERGE_SKIP
def test_should_merge_when_all_reports_have_undefined_report_file_path():
    """should merge when all reports have undefined reportFilePath"""
    pass


@_MERGE_SKIP
def test_should_use_constant_memory_when_merging_reports_with_large_inline_images():
    """should use constant memory when merging reports with large inline images"""
    pass


_MERGE_DEDUP_SKIP = pytest.mark.skip(
    reason="Python has no merge pipeline that writes and deduplicates inline "
    "midscene-image script tags across merged reports"
)


@_MERGE_DEDUP_SKIP
def test_should_store_a_shared_inline_reference_image_once_when_merging_reports():
    """should store a shared inline reference image once when merging reports"""
    pass
