"""Shared-browser YAML batch orchestration (upstream shared-browser-batch.test.ts).

The upstream suite exercises Puppeteer ``Browser``/``BrowserContext`` sharing.
The Python batch runner accepts an injected player factory and does not manage
browsers, so every case here is Node-only.
"""

import pytest

_SKIP = "Python batch runner does not manage Puppeteer browsers"


class TestSharedBrowserBatch:
    @pytest.mark.skip(reason=_SKIP)
    def test_shares_one_browser_context_while_leaving_page_creation_to_the_web_launcher(
        self,
    ):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_passes_shared_browser_chrome_launch_options(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_does_not_launch_a_shared_browser_when_sharing_is_disabled(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_does_not_launch_puppeteer_for_a_non_web_batch(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_connects_and_disconnects_instead_of_closing_in_shared_cdp_mode(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_runs_setup_before_the_main_files(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_aborts_main_files_when_setup_fails(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_aborts_main_files_when_setup_is_partially_successful(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_exposes_unexpected_setup_failures_through_the_typed_batch_error(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_rejects_setup_without_a_shared_browser_context(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_rejects_a_file_used_as_both_setup_and_a_main_file(self):
        pass
