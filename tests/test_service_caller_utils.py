"""Synced from upstream service-caller retry/error helpers (utils.ts)."""

import pytest


def test_internal_call_id_field_matches_upstream():
    from midscene.core.ai_model.service_caller.utils import (
        INTERNAL_CALL_ID_FIELD,
        build_usage_info,
    )

    assert INTERNAL_CALL_ID_FIELD == "_midscene_call_id"
    usage = build_usage_info(
        raw_usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        model_config={"modelName": "m", "modelDescription": "d"},
        time_cost=10,
        retry_count=0,
        request_id=None,
        response_model_name=None,
        internal_call_id="call_1",
    )
    assert usage[INTERNAL_CALL_ID_FIELD] == "call_1"


def test_stringify_for_debug_falls_back_to_string():
    from midscene.core.ai_model.service_caller.utils import stringify_for_debug

    assert stringify_for_debug({"a": 1}) == '{"a": 1}'

    class Unserializable:
        def __repr__(self):
            return "<unserializable>"

    assert stringify_for_debug(Unserializable()) == "<unserializable>"


def test_to_error_preserves_exceptions_and_wraps_values():
    from midscene.core.ai_model.service_caller.utils import to_error

    error = RuntimeError("boom")
    assert to_error(error) is error

    wrapped = to_error("boom")
    assert isinstance(wrapped, Exception)
    assert str(wrapped) == "boom"


def test_append_failure_summary_reports_retry_counts_and_last_error():
    from midscene.core.ai_model.service_caller.utils import (
        append_ai_request_failure_summary,
    )

    error = RuntimeError("second failure")
    result = append_ai_request_failure_summary(
        error,
        [
            {"attempt": 1, "error": RuntimeError("first failure")},
            {"attempt": 2, "error": error},
        ],
        3,
    )

    assert result is error
    message = str(error)
    assert "AI model request failed after 1 retry (2/3 attempts)" in message
    assert "Last error: second failure" in message
    assert "Previous AI call attempt errors:" in message
    assert "Attempt 1: first failure" in message


def test_append_failure_summary_omits_previous_errors_for_a_single_attempt():
    from midscene.core.ai_model.service_caller.utils import (
        append_ai_request_failure_summary,
    )

    error = RuntimeError("single failure")
    append_ai_request_failure_summary(error, [{"attempt": 1, "error": error}], 1)

    message = str(error)
    assert "after 0 retries (1/1 attempts)" in message
    assert "Previous AI call attempt errors" not in message


def test_normalize_retry_count_matches_upstream_rules():
    from midscene.core.ai_model.service_caller.utils import normalize_retry_count

    assert normalize_retry_count(None) == 1
    assert normalize_retry_count(float("nan")) == 1
    assert normalize_retry_count(float("inf")) == 1
    assert normalize_retry_count(-1) == 0
    assert normalize_retry_count(2.9) == 2


@pytest.mark.parametrize("value", [None, False, 0])
def test_to_error_wraps_falsey_values(value):
    from midscene.core.ai_model.service_caller.utils import to_error

    assert isinstance(to_error(value), Exception)
