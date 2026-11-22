"""Shared helpers (upstream packages/shared/tests/unit-test/utils.test.ts)."""

import asyncio
import uuid as uuid_module

import pytest

from midscene.shared.utils import (
    assert_,
    escape_script_tag,
    anti_escape_script_tag,
    generate_hash_id,
    if_in_browser,
    if_in_node,
    if_in_worker,
    is_plain_object,
    log_msg,
    merge_and_normalize_app_name_mapping,
    normalize_for_comparison,
    repeat,
    replace_illegal_path_chars_and_space,
    sha256_hex,
    uuid,
)


class TestNormalizeForComparison:
    def test_should_convert_to_lowercase(self):
        assert normalize_for_comparison("MockApp") == "mockapp"
        assert normalize_for_comparison("MOCKAPP") == "mockapp"
        assert normalize_for_comparison("mockapp") == "mockapp"

    def test_should_remove_spaces(self):
        assert normalize_for_comparison("Mock App") == "mockapp"
        assert normalize_for_comparison("mock app") == "mockapp"
        assert normalize_for_comparison("Mock  App") == "mockapp"

    def test_should_handle_multiple_spaces(self):
        assert normalize_for_comparison("Mock   App   Name") == "mockappname"
        assert normalize_for_comparison("  Mock App  ") == "mockapp"

    def test_should_handle_tabs_and_newlines(self):
        assert normalize_for_comparison("Mock\tApp") == "mockapp"
        assert normalize_for_comparison("Mock\nApp") == "mockapp"

    def test_should_match_different_variations_of_the_same_app_name(self):
        mapping_key = "Mock App"
        normalized_key = normalize_for_comparison(mapping_key)

        user_inputs = [
            "mockapp",
            "MockApp",
            "MOCKAPP",
            "Mock App",
            "mock app",
            "MOCK APP",
            "Mock  App",
            "  MockApp  ",
        ]

        for user_input in user_inputs:
            assert normalize_for_comparison(user_input) == normalized_key

    def test_should_remove_dashes(self):
        assert normalize_for_comparison("Mock-App") == "mockapp"
        assert normalize_for_comparison("mock-app") == "mockapp"
        assert normalize_for_comparison("Google-Calendar") == "googlecalendar"
        assert normalize_for_comparison("Google-Play-Store") == "googleplaystore"

    def test_should_remove_underscores(self):
        assert normalize_for_comparison("Mock_App") == "mockapp"
        assert normalize_for_comparison("mock_app") == "mockapp"
        assert normalize_for_comparison("Google_Calendar") == "googlecalendar"
        assert normalize_for_comparison("Google_Play_Store") == "googleplaystore"

    def test_should_handle_mixed_separators(self):
        assert normalize_for_comparison("Mock-App_Name") == "mockappname"
        assert normalize_for_comparison("Mock_App-Name") == "mockappname"
        assert normalize_for_comparison("Mock App-Name_Test") == "mockappnametest"
        assert normalize_for_comparison("Google-Calendar_App") == "googlecalendarapp"

    def test_should_match_app_names_with_different_separator_variations(self):
        variations = [
            "Google Calendar",
            "Google-Calendar",
            "Google_Calendar",
            "google calendar",
            "google-calendar",
            "google_calendar",
            "GoogleCalendar",
            "googlecalendar",
            "GOOGLE CALENDAR",
            "GOOGLE-CALENDAR",
            "GOOGLE_CALENDAR",
        ]

        for normalized in (normalize_for_comparison(v) for v in variations):
            assert normalized == "googlecalendar"

    def test_should_handle_consecutive_separators(self):
        assert normalize_for_comparison("Mock--App") == "mockapp"
        assert normalize_for_comparison("Mock__App") == "mockapp"
        assert normalize_for_comparison("Mock--_-App") == "mockapp"
        assert normalize_for_comparison("Mock  -  App") == "mockapp"


class TestMergeAndNormalizeAppNameMapping:
    def test_should_normalize_mapping_keys_with_later_entries_winning(self):
        mapping = {
            "Google Calendar": "com.google.android.calendar",
            "Google-Calendar": "com.google.android.calendar.v2",
        }

        normalized = merge_and_normalize_app_name_mapping(mapping)

        assert len(normalized) == 1
        assert normalized["googlecalendar"] == "com.google.android.calendar.v2"

    def test_should_handle_mixed_case_and_separators(self):
        mapping = {
            "Google Play Store": "com.android.vending",
            "GooglePlayStore": "com.android.vending.alt",
            "google-play-store": "com.android.vending.final",
        }

        normalized = merge_and_normalize_app_name_mapping(mapping)

        assert len(normalized) == 1
        assert normalized["googleplaystore"] == "com.android.vending.final"

    def test_should_preserve_unique_entries(self):
        mapping = {
            "Chrome": "com.android.chrome",
            "Firefox": "org.mozilla.firefox",
            "Safari": "com.apple.safari",
        }

        normalized = merge_and_normalize_app_name_mapping(mapping)

        assert len(normalized) == 3
        assert normalized["chrome"] == "com.android.chrome"
        assert normalized["firefox"] == "org.mozilla.firefox"
        assert normalized["safari"] == "com.apple.safari"

    def test_should_handle_empty_mapping(self):
        assert merge_and_normalize_app_name_mapping({}) == {}

    def test_should_merge_user_mapping_over_default_with_normalized_keys(self):
        default_mapping = {
            "Google Calendar": "com.google.android.calendar",
            "Chrome": "com.android.chrome",
        }

        user_mapping = {
            "google-calendar": "com.custom.calendar",
        }

        merged = merge_and_normalize_app_name_mapping(default_mapping, user_mapping)

        assert merged["googlecalendar"] == "com.custom.calendar"
        assert merged["chrome"] == "com.android.chrome"

    def test_should_handle_undefined_user_mapping(self):
        default_mapping = {
            "Chrome": "com.android.chrome",
        }

        result = merge_and_normalize_app_name_mapping(default_mapping, None)

        assert result["chrome"] == "com.android.chrome"

    def test_should_allow_user_to_override_with_different_separator_style(self):
        default_mapping = {
            "Google Calendar": "com.google.android.calendar",
            "Google Drive": "com.google.android.apps.docs",
        }

        user_mapping = {
            "google_calendar": "com.custom.calendar",
        }

        merged = merge_and_normalize_app_name_mapping(default_mapping, user_mapping)

        assert merged["googlecalendar"] == "com.custom.calendar"
        assert merged["googledrive"] == "com.google.android.apps.docs"


class TestReplaceIllegalPathCharsAndSpace:
    """Ported from upstream replaceIllegalPathCharsAndSpace cases."""

    def test_should_preserve_unix_path_separators(self):
        assert (
            replace_illegal_path_chars_and_space("/path/to/file.txt")
            == "/path/to/file.txt"
        )

    def test_should_preserve_windows_backslash_separators_but_replace_colon(self):
        assert (
            replace_illegal_path_chars_and_space("C:\\Users\\Documents\\file.txt")
            == "C-\\Users\\Documents\\file.txt"
        )

    def test_should_replace_illegal_filename_characters_with_dashes(self):
        assert (
            replace_illegal_path_chars_and_space(
                'file:name*with?illegal"chars<>|.txt'
            )
            == "file-name-with-illegal-chars---.txt"
        )

    def test_should_replace_spaces_with_dashes(self):
        assert (
            replace_illegal_path_chars_and_space("file name with spaces.txt")
            == "file-name-with-spaces.txt"
        )

    def test_should_handle_mixed_path_and_illegal_characters(self):
        assert (
            replace_illegal_path_chars_and_space(
                '/path/to/file:with*illegal?chars<>|.txt'
            )
            == "/path/to/file-with-illegal-chars---.txt"
        )

    def test_should_handle_windows_path_with_illegal_characters(self):
        assert (
            replace_illegal_path_chars_and_space(
                'C:\\Users\\Documents\\file:name*with?illegal"chars<>|.txt'
            )
            == 'C-\\Users\\Documents\\file-name-with-illegal-chars---.txt'
        )

    def test_should_handle_empty_string(self):
        assert replace_illegal_path_chars_and_space("") == ""

    def test_should_handle_string_with_only_illegal_characters(self):
        assert replace_illegal_path_chars_and_space(':*?"<>| ') == "--------"

    def test_should_handle_string_with_only_path_separators(self):
        assert replace_illegal_path_chars_and_space("/\\//\\") == "/\\//\\"

    def test_should_handle_complex_real_world_scenario(self):
        assert (
            replace_illegal_path_chars_and_space(
                '/Users/test/Documents/My Project: "Important File" '
                "<2024>|backup*.txt"
            )
            == "/Users/test/Documents/My-Project---Important-File---2024--backup-.txt"
        )

    def test_should_handle_task_title_with_illegal_characters(self):
        assert (
            replace_illegal_path_chars_and_space(
                'Task: "Test File" <Important>|Special*'
            )
            == "Task---Test-File---Important--Special-"
        )

    def test_should_handle_cache_id_with_mixed_characters(self):
        assert (
            replace_illegal_path_chars_and_space(
                'cache-id:with*special?chars"and<spaces>|'
            )
            == "cache-id-with-special-chars-and-spaces--"
        )

    def test_should_replace_hash_symbol_with_dash(self):
        assert (
            replace_illegal_path_chars_and_space("file#with#hash#symbols.txt")
            == "file-with-hash-symbols.txt"
        )


class TestGenerateHashId:
    def test_should_produce_stable_ids(self):
        rect = {"left": 1, "top": 2, "width": 3, "height": 4}
        assert generate_hash_id(rect, "same") == generate_hash_id(rect, "same")

    def test_should_differ_for_different_content(self):
        rect = {"left": 1, "top": 2, "width": 3, "height": 4}
        assert generate_hash_id(rect, "aaa") != generate_hash_id(rect, "bbb")

    def test_should_differ_for_different_rects(self):
        assert generate_hash_id({"left": 0}, "same") != generate_hash_id(
            {"left": 1}, "same"
        )

    def test_should_serialize_integral_floats_like_json_stringify(self):
        # JS JSON.stringify(1.0) === "1"; a Python float must not change the id.
        assert generate_hash_id({"left": 1.0}, "same") == generate_hash_id(
            {"left": 1}, "same"
        )


class TestSha256Hex:
    def test_should_hash_utf8(self):
        assert (
            sha256_hex("abc")
            == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )


class TestAssert:
    def test_should_raise_with_message(self):
        with pytest.raises(AssertionError, match="boom"):
            assert_(False, "boom")

    def test_should_use_default_message(self):
        with pytest.raises(AssertionError, match="Assertion failed"):
            assert_(0)

    def test_should_pass_truthy_conditions(self):
        assert_(1)


class TestIsPlainObject:
    def test_should_accept_objects(self):
        assert is_plain_object({}) is True
        assert is_plain_object({"a": 1}) is True

    def test_should_reject_null_and_arrays(self):
        assert is_plain_object(None) is False
        assert is_plain_object([]) is False
        assert is_plain_object("value") is False


class TestRepeat:
    def test_should_await_fn_times(self):
        seen = []

        async def record(index):
            seen.append(index)

        asyncio.run(repeat(3, record))
        assert seen == [0, 1, 2]


class TestMisc:
    def test_should_generate_uuid_v4(self):
        value = uuid()
        assert uuid_module.UUID(value).version == 4

    def test_should_detect_node_runtime(self):
        assert if_in_browser is False
        assert if_in_worker is False
        assert if_in_node is True

    def test_should_log_to_stdout(self, capsys):
        log_msg("hello", "world")
        assert capsys.readouterr().out == "hello world\n"

    def test_script_tag_escaping_roundtrip(self):
        escaped = escape_script_tag("<script>alert(1)</script>")
        assert "<" not in escaped and ">" not in escaped
        assert anti_escape_script_tag(escaped) == "<script>alert(1)</script>"
