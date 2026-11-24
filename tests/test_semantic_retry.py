"""Synced from upstream packages/core/tests/unit-test/semantic-retry.test.ts.

Cancellation mirrors the upstream ``abortSignal``: an aborted signal is
observed before the call, after a successful parse, after a parse failure,
and after ``onParseRetry``/the retry delay.
"""

import asyncio

import pytest

from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)
from midscene.shared.types import AbortError, AbortSignal


@pytest.mark.asyncio
async def test_preserves_cancellation_when_asynchronous_parsing_succeeds_after_cancellation():
    """preserves cancellation when asynchronous parsing succeeds after cancellation"""
    signal = AbortSignal()
    reason = "cancelled during parsing"
    calls = []
    parse_errors = []

    async def call_ai(retry_attempt, previous_parse_error=None):
        calls.append(retry_attempt)
        return "response"

    async def parse_response(_response):
        await asyncio.sleep(0)
        signal.abort(reason)
        return "parsed"

    def to_parse_error(error, response):
        parse_errors.append(error)
        return RuntimeError("parse failed")

    with pytest.raises(AbortError, match=reason):
        await call_ai_and_parse_with_retry(
            call_ai=call_ai,
            parse_response=parse_response,
            to_parse_error=to_parse_error,
            parse_retry_times=1,
            abort_signal=signal,
        )

    assert calls == [0]
    assert parse_errors == []


@pytest.mark.asyncio
async def test_preserves_cancellation_when_parsing_fails_after_the_signal_is_aborted():
    """preserves cancellation when parsing fails after the signal is aborted"""
    signal = AbortSignal()
    reason = "cancelled during parsing"
    calls = []
    parse_errors = []

    async def call_ai(retry_attempt, previous_parse_error=None):
        calls.append(retry_attempt)
        return "response"

    def parse_response(_response):
        signal.abort(reason)
        raise ValueError("invalid response")

    def to_parse_error(error, response):
        parse_errors.append(error)
        return RuntimeError("parse failed")

    with pytest.raises(AbortError, match=reason):
        await call_ai_and_parse_with_retry(
            call_ai=call_ai,
            parse_response=parse_response,
            to_parse_error=to_parse_error,
            parse_retry_times=1,
            abort_signal=signal,
        )

    assert calls == [0]
    assert parse_errors == []


@pytest.mark.asyncio
async def test_preserves_cancellation_from_onparseretry_with_no_retry_delay():
    """preserves cancellation from onParseRetry with no retry delay"""
    signal = AbortSignal()
    reason = "cancelled by caller"
    calls = []
    parse_errors = []

    async def call_ai(retry_attempt, previous_parse_error=None):
        calls.append(retry_attempt)
        return "invalid"

    def parse_response(_response):
        raise ValueError("invalid response")

    def to_parse_error(error, response):
        parse_errors.append(error)
        return RuntimeError("parse failed")

    with pytest.raises(AbortError, match=reason):
        await call_ai_and_parse_with_retry(
            call_ai=call_ai,
            parse_response=parse_response,
            to_parse_error=to_parse_error,
            parse_retry_times=1,
            parse_retry_interval=0,
            abort_signal=signal,
            on_parse_retry=lambda _error, _response: signal.abort(reason),
        )

    assert calls == [0]
    assert parse_errors == []


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
        to_parse_error=lambda error, response: (
            error if isinstance(error, Exception) else RuntimeError(str(error))
        ),
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
                "failed to parse LLM response into JSON. Response -\n"
                '{"untrusted":"raw response"}\n\n'
                "Please avoid the validation error above in this response."
            ),
        },
    ]
