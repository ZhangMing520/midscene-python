"""Synced from upstream packages/core/tests/unit-test/semantic-retry.test.ts.

The Python retry loop has no abort-signal parameter (cancellation is expected
to propagate as task cancellation), so the three upstream cancellation cases
are skipped. The retry/feedback behavior is ported directly.
"""

import pytest

from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)

_ABORT_SKIP = pytest.mark.skip(
    reason="Python call_ai_and_parse_with_retry has no abortSignal parameter to "
    "observe cancellation during parsing/retry"
)


@_ABORT_SKIP
@pytest.mark.asyncio
async def test_preserves_cancellation_when_asynchronous_parsing_succeeds_after_cancellation():
    """preserves cancellation when asynchronous parsing succeeds after cancellation"""
    pass


@_ABORT_SKIP
@pytest.mark.asyncio
async def test_preserves_cancellation_when_parsing_fails_after_the_signal_is_aborted():
    """preserves cancellation when parsing fails after the signal is aborted"""
    pass


@_ABORT_SKIP
@pytest.mark.asyncio
async def test_preserves_cancellation_from_onparseretry_with_no_retry_delay():
    """preserves cancellation from onParseRetry with no retry delay"""
    pass


@pytest.mark.asyncio
async def test_increments_the_semantic_retry_attempt_after_parsing_failures():
    """increments the semantic retry attempt after parsing failures"""
    attempts = []
    previous_errors = []

    async def call_ai(retry_attempt, previous_parse_error):
        attempts.append(retry_attempt)
        previous_errors.append(
            str(previous_parse_error)
            if isinstance(previous_parse_error, BaseException)
            else None
        )
        return retry_attempt

    def parse_response(response):
        if response == 0:
            raise ValueError("invalid response")
        return response

    result = await call_ai_and_parse_with_retry(
        call_ai=call_ai,
        parse_response=parse_response,
        to_parse_error=lambda error, response: error
        if isinstance(error, Exception)
        else RuntimeError(str(error)),
        parse_retry_times=1,
    )

    assert result == 1
    assert attempts == [0, 1]
    assert previous_errors == [None, "invalid response"]


def test_adds_the_complete_validation_error_message_to_retry_feedback():
    """adds the complete validation error message to retry feedback"""
    messages = with_semantic_retry_feedback(
        [{"role": "user", "content": "original request"}],
        ValueError(
            'failed to parse LLM response into JSON. Response -\n{"untrusted":"raw response"}'
        ),
    )

    assert messages == [
        {"role": "user", "content": "original request"},
        {
            "role": "user",
            "content": (
                "The previous response was invalid:\n"
                'failed to parse LLM response into JSON. Response -\n'
                '{"untrusted":"raw response"}\n\n'
                "Please avoid the validation error above in this response."
            ),
        },
    ]
