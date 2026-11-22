"""Synced from upstream packages/core/tests/unit-test/service-caller-timeout.test.ts."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tests.core_helpers import FakeResponse


def _chat_completion_payload(content: str = "ok") -> Dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "model": "mock-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


class _StubAsyncClient:
    def __init__(self, responses):
        self._responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        return next(self._responses)


class TestServiceCallerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_passed_to_httpx_in_seconds(self):
        from midscene.core.ai_model.service_caller import model_call

        captured: List[Dict[str, Any]] = []

        class RecordingClient(_StubAsyncClient):
            def __init__(self, *args, **kwargs):
                captured.append(kwargs)
                super().__init__([FakeResponse(_chat_completion_payload())])

        with patch.object(
            model_call.httpx,
            "AsyncClient",
            lambda *a, **k: RecordingClient(*a, **k),
        ):
            await model_call._post_json(
                url="https://example.com/v1/chat/completions",
                headers={},
                request_body={"model": "m", "messages": []},
                effective_timeout=5000,
                proxy=None,
                stream=False,
            )

        assert captured[0]["timeout"].read == 5.0

    def test_default_timeout_is_180s(self):
        from midscene.core.ai_model.service_caller.request_timeout import (
            DEFAULT_AI_CALL_TIMEOUT_MS,
            resolve_effective_timeout_ms,
        )

        assert DEFAULT_AI_CALL_TIMEOUT_MS == 180_000
        assert resolve_effective_timeout_ms(None) == 180_000.0
        assert resolve_effective_timeout_ms(0) is None
        assert resolve_effective_timeout_ms(2500) == 2500.0

    def test_timeout_error_code_and_message_match_upstream(self):
        from midscene.core.ai_model.service_caller.request_timeout import (
            AI_CALL_HARD_TIMEOUT_CODE,
            AIRequestTimeoutError,
        )

        error = AIRequestTimeoutError(50.0)

        assert error.code == AI_CALL_HARD_TIMEOUT_CODE
        assert error.name == "AIRequestTimeoutError"
        assert error.timeout_ms == 50.0
        assert str(error) == (
            "AI call hard timeout after 50ms (full request time exceeded)"
        )

    def test_identifies_hard_timeout_errors_both_directly_and_through_cause_chains(
        self,
    ):
        from midscene.core.ai_model.service_caller.request_timeout import (
            AI_CALL_HARD_TIMEOUT_CODE,
            AIRequestTimeoutError,
            is_hard_timeout_error,
        )

        direct = AIRequestTimeoutError(10)
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = direct

        assert AI_CALL_HARD_TIMEOUT_CODE == "AI_CALL_HARD_TIMEOUT"
        assert direct.code == AI_CALL_HARD_TIMEOUT_CODE
        assert is_hard_timeout_error(direct) is True
        assert is_hard_timeout_error(wrapped) is True
        assert is_hard_timeout_error(RuntimeError("other")) is False

    def test_cleans_up_the_injected_timer_so_it_does_not_auto_abort_after_success(
        self,
    ):
        import time

        from midscene.core.ai_model.service_caller.request_timeout import (
            build_request_abort_signal,
        )

        handle = build_request_abort_signal(20)
        handle.cleanup()
        time.sleep(0.04)

        assert handle.signal.aborted is False

    def test_forwards_an_already_aborted_caller_signal_immediately(self):
        from midscene.core.ai_model.service_caller.request_timeout import (
            build_request_abort_signal,
        )
        from midscene.shared.types import AbortSignal

        user_signal = AbortSignal()
        reason = RuntimeError("caller already cancelled")
        user_signal.abort(reason)

        handle = build_request_abort_signal(60_000, user_signal)

        assert handle.signal.aborted is True
        assert handle.signal.reason is reason


@pytest.mark.asyncio
async def test_exposes_a_typed_timeout_reason_directly_from_the_abort_race():
    import asyncio

    from midscene.core.ai_model.service_caller.request_timeout import (
        AIRequestTimeoutError,
        build_request_abort_signal,
        run_with_abort_signal,
    )

    handle = build_request_abort_signal(10)

    async def never_completes():
        await asyncio.Event().wait()

    try:
        with pytest.raises(AIRequestTimeoutError) as exc_info:
            await run_with_abort_signal(handle.signal, never_completes)
        assert exc_info.value is handle.signal.reason
        assert exc_info.value.timeout_ms == 10
    finally:
        handle.cleanup()


@pytest.mark.asyncio
async def test_keeps_a_request_failure_that_wins_the_race_instead_of_relabelling_it_as_timeout():
    import asyncio

    from midscene.core.ai_model.service_caller.request_timeout import (
        AIRequestTimeoutError,
        run_with_abort_signal,
    )
    from midscene.shared.types import AbortSignal

    signal = AbortSignal()
    failure = RuntimeError("connection failed")

    async def operation():
        asyncio.get_running_loop().call_soon(
            signal.abort, AIRequestTimeoutError(10)
        )
        raise failure

    with pytest.raises(RuntimeError) as exc_info:
        await run_with_abort_signal(signal, operation)

    assert exc_info.value is failure


@pytest.mark.asyncio
async def test_wait_for_retry_resolves_after_the_delay():
    import time

    from midscene.core.ai_model.service_caller.request_timeout import (
        wait_for_retry,
    )

    started = time.monotonic()
    await wait_for_retry(20)
    assert time.monotonic() - started >= 0.015


@pytest.mark.asyncio
async def test_wait_for_retry_stops_promptly_when_cancelled():
    import asyncio

    from midscene.core.ai_model.service_caller.request_timeout import (
        wait_for_retry,
    )
    from midscene.shared.types import AbortError, AbortSignal

    signal = AbortSignal()
    asyncio.get_running_loop().call_later(0.01, signal.abort, "stop")

    with pytest.raises(AbortError):
        await wait_for_retry(60_000, signal)

