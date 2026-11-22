"""Shared helpers (upstream packages/shared/tests/unit-test/utils.test.ts)."""

from midscene.shared.utils import (
    merge_and_normalize_app_name_mapping,
    normalize_for_comparison,
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
