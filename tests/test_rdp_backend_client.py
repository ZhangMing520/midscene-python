"""Synced from upstream
``packages/computer/tests/unit-test/rdp/backend-client.test.ts``.

The Python port has no ``HelperProcessRDPBackendClient``: no rdp-helper
subprocess transport is bundled, so ``UnsupportedRDPBackendClient`` is the
default and every helper-process case is skipped.
"""

import pytest

_SKIP_REASON = (
    "Python computer/rdp/backend_client.py has no HelperProcessRDPBackendClient "
    "or rdp-helper subprocess transport; the default "
    "UnsupportedRDPBackendClient raises without spawning a helper"
)


@pytest.mark.skip(reason=_SKIP_REASON)
def test_parses_successful_helper_responses():
    """parses successful helper responses"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_normalizes_bracketed_ipv6_hosts_before_sending_helper_connect_requests():
    """normalizes bracketed IPv6 hosts before sending helper connect requests"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_forwards_local_address_in_helper_connect_requests():
    """forwards localAddress in helper connect requests"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_rejects_structured_helper_errors():
    """rejects structured helper errors"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_rejects_all_pending_requests_if_the_helper_exits_unexpectedly():
    """rejects all pending requests if the helper exits unexpectedly"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_rejects_pending_requests_if_the_helper_stdin_pipe_breaks():
    """rejects pending requests if the helper stdin pipe breaks"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_includes_helper_diagnostics_when_the_first_connect_write_fails_after_early_helper_exit():
    """includes helper diagnostics when the first connect write fails after early helper exit"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_rejects_old_helper_pending_requests_after_a_reconnect_starts_a_new_helper():
    """rejects old helper pending requests after a reconnect starts a new helper"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_throws_on_malformed_helper_output():
    """throws on malformed helper output"""
    pass


@pytest.mark.skip(reason=_SKIP_REASON)
def test_surfaces_the_original_helper_exit_instead_of_silently_restarting_an_empty_helper():
    """surfaces the original helper exit instead of silently restarting an empty helper"""
    pass
