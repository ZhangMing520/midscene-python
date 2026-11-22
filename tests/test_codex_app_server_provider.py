"""Synced from upstream packages/core/tests/unit-test/codex-app-server-provider.test.ts.

The upstream tests spawn a fake ``codex app-server`` executable and speak the
same line-delimited JSON-RPC protocol. Here the child process is replaced with
an in-process fake that exposes the same ``stdin``/``stdout``/``stderr``/``wait``
surface used by ``CodexAppServerConnection``.
"""

import asyncio
import copy
import json
from typing import Any, Dict, List, Optional

import pytest

from midscene.core.ai_model.model_adapter.codex_app_server import (
    build_default_codex_app_server_params,
)
from midscene.core.ai_model.models.registry import get_model_runtime
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.service_caller.codex import (
    codex_app_server as codex_module,
)
from midscene.core.ai_model.service_caller.codex.codex_app_server import (
    __shutdown_codex_app_server_for_tests,
    build_codex_turn_payload_from_messages,
    call_ai_with_codex_app_server,
    is_codex_app_server_provider,
    normalize_codex_local_image_path,
)

BASE_MODEL_CONFIG: Dict[str, Any] = {
    "modelName": "gpt-5.4",
    "modelDescription": "codex",
    "intent": "default",
    "slot": "default",
}


class FakeReader:
    """Minimal ``asyncio.StreamReader`` stand-in backed by a queue."""

    def __init__(self) -> None:
        self._queue: "asyncio.Queue[bytes]" = asyncio.Queue()

    def feed(self, message: Dict[str, Any]) -> None:
        self._queue.put_nowait((json.dumps(message) + "\n").encode("utf-8"))

    async def readline(self) -> bytes:
        return await self._queue.get()


class FakeStdin:
    def __init__(self, on_message) -> None:
        self.on_message = on_message
        self.closed = False

    def write(self, data: bytes) -> None:
        text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
        for line in text.splitlines():
            if line.strip():
                self.on_message(json.loads(line))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeCodexAppServerProcess:
    """A fake ``codex app-server`` process with a canned turn transcript."""

    def __init__(self, hold_turns: bool = False) -> None:
        self.stdin = FakeStdin(self._handle_message)
        self.stdout = FakeReader()
        self.stderr = FakeReader()
        self.returncode: Optional[int] = None
        self.received: List[Dict[str, Any]] = []
        self.request_log = ""
        self.turn_started = asyncio.Event()
        self._hold_turns = hold_turns
        self._released = not hold_turns
        self._done = asyncio.Event()

    def _reply(
        self, message: Dict[str, Any], result: Any = None, error: Any = None
    ) -> None:
        payload: Dict[str, Any] = {"id": message.get("id")}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        self.stdout.feed(payload)

    def _handle_message(self, message: Dict[str, Any]) -> None:
        self.received.append(message)
        method = message.get("method")

        if method == "initialize":
            self._reply(message, {})
        elif method == "thread/start":
            self.request_log += "thread/start\n"
            self._reply(message, {"thread": {"id": "thread-1"}})
        elif method == "turn/start":
            self._reply(message, {"turn": {"id": "turn-1"}})
            self._emit_turn_events()
            self.turn_started.set()
            if self._released:
                self._emit_turn_completed()
        elif method in ("thread/unsubscribe", "turn/interrupt"):
            self._reply(message, {})
        elif method == "initialized":
            return
        else:
            self._reply(
                message,
                error={"code": -32601, "message": f"unknown method {method}"},
            )

    def _emit_turn_events(self) -> None:
        self.stdout.feed(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "delta": "hello",
                },
            }
        )
        self.stdout.feed(
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "tokenUsage": {
                        "last": {
                            "inputTokens": 10,
                            "outputTokens": 5,
                            "totalTokens": 15,
                            "cachedInputTokens": 3,
                            "reasoningOutputTokens": 2,
                        }
                    },
                },
            }
        )

    def _emit_turn_completed(self) -> None:
        self.stdout.feed(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "turn-1", "status": "completed"},
                },
            }
        )

    def release_turn(self) -> None:
        if self._released:
            return
        self._released = True
        self._emit_turn_completed()

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()

    async def wait(self) -> Optional[int]:
        await self._done.wait()
        return self.returncode


def install_fake_process(monkeypatch, hold_turns: bool = False):
    process = FakeCodexAppServerProcess(hold_turns=hold_turns)

    async def fake_spawn():
        return process

    monkeypatch.setattr(codex_module, "_spawn_codex_app_server", fake_spawn)
    return process


def resolve_image_detail(input_data: Dict[str, Any]) -> str:
    return input_data.get("imageDetail") or "high"


def test_detects_codex_provider_base_url() -> None:
    assert is_codex_app_server_provider("codex://app-server") is True
    assert is_codex_app_server_provider("  CODEX://APP-SERVER  ") is True
    assert is_codex_app_server_provider("https://api.openai.com/v1") is False
    assert is_codex_app_server_provider(None) is False


def test_preserves_default_codex_parameter_handling_for_other_model_families() -> None:
    assert build_default_codex_app_server_params({})["config"] == {
        "effort": "none"
    }
    assert build_default_codex_app_server_params(
        {"userConfig": {"reasoningEnabled": True}}
    )["config"] == {"effort": "medium"}
    assert build_default_codex_app_server_params(
        {"userConfig": {"reasoningEnabled": True, "reasoningEffort": " XHIGH "}}
    )["config"] == {"effort": "xhigh"}
    assert build_default_codex_app_server_params(
        {"userConfig": {"reasoningEnabled": True, "reasoningEffort": "invalid"}}
    )["config"] == {"effort": "medium"}


def test_converts_conversation_messages_into_codex_turn_payload() -> None:
    messages = [
        {"role": "system", "content": "System rule: return concise output."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Please inspect this screenshot."},
                {"type": "image", "url": "https://example.com/image.png"},
                {"type": "image", "url": "file:///tmp/local-shot.png"},
            ],
        },
        {"role": "assistant", "content": "I will check it now."},
    ]

    payload = build_codex_turn_payload_from_messages(
        messages, resolve_image_detail
    )

    assert "System rule: return concise output." in payload["developerInstructions"]
    assert payload["input"][0]["type"] == "text"
    assert "[USER]" in payload["input"][0]["text"]
    assert "Please inspect this screenshot." in payload["input"][0]["text"]
    assert "[ASSISTANT]" in payload["input"][0]["text"]
    assert {
        "type": "image",
        "url": "https://example.com/image.png",
        "detail": "high",
    } in payload["input"]
    assert {
        "type": "localImage",
        "path": "/tmp/local-shot.png",
        "detail": "high",
    } in payload["input"]


def test_converts_history_entries_directly_and_applies_image_detail_without_mutating_history() -> (
    None
):
    messages: List[Dict[str, Any]] = [
        {
            "type": "input-message",
            "message": {"role": "system", "content": "System rule"},
        },
        {
            "type": "input-message",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Inspect screenshot"},
                    {"type": "image", "url": "https://example.com/image.png"},
                ],
            },
        },
        {
            "type": "model-output",
            "output": {
                "type": "chat-completion",
                "rawValue": {
                    "role": "assistant",
                    "content": "Previous answer",
                    "refusal": None,
                },
            },
        },
    ]
    original = copy.deepcopy(messages)

    payload = build_codex_turn_payload_from_messages(
        messages, lambda _input_data: "original"
    )

    assert payload["developerInstructions"] == "System rule"
    assert payload["input"][0]["type"] == "text"
    assert (
        payload["input"][0]["text"]
        == "[USER]\nInspect screenshot\n\n[ASSISTANT]\nPrevious answer"
    )
    assert {
        "type": "image",
        "url": "https://example.com/image.png",
        "detail": "original",
    } in payload["input"]
    assert messages == original


def test_rejects_responses_output_in_codex_history() -> None:
    with pytest.raises(
        ValueError, match="Cannot replay Responses output in a Codex conversation"
    ):
        build_codex_turn_payload_from_messages(
            [
                {
                    "type": "model-output",
                    "output": {"type": "responses", "rawValue": []},
                }
            ],
            resolve_image_detail,
        )


def test_preserves_image_detail_in_codex_turn_inputs() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Check this."},
                {"type": "image", "url": "https://example.com/img.png"},
            ],
        }
    ]

    payload = build_codex_turn_payload_from_messages(
        messages, resolve_image_detail
    )

    assert {
        "type": "image",
        "url": "https://example.com/img.png",
        "detail": "high",
    } in payload["input"]


def test_overrides_image_detail_in_codex_turn_inputs_when_required_by_adapter() -> (
    None
):
    messages = [
        {
            "role": "user",
            "content": [{"type": "image", "url": "file:///tmp/local-shot.png"}],
        }
    ]

    payload = build_codex_turn_payload_from_messages(
        messages, lambda _input_data: "original"
    )

    assert "detail" not in messages[0]["content"][0]
    assert {
        "type": "localImage",
        "path": "/tmp/local-shot.png",
        "detail": "original",
    } in payload["input"]


def test_keeps_the_newest_transcript_context_when_truncating_long_turns() -> None:
    old_content = f"old-prefix-{'a' * 270_000}"
    latest_request = "latest user request should survive truncation"
    payload = build_codex_turn_payload_from_messages(
        [
            {"role": "user", "content": old_content},
            {"role": "assistant", "content": "intermediate assistant response"},
            {"role": "user", "content": latest_request},
        ],
        resolve_image_detail,
    )

    text = payload["input"][0]["text"]
    assert payload["input"][0]["type"] == "text"
    assert latest_request in text
    assert "old-prefix-" not in text
    assert len(text) <= 256 * 1024


def test_normalizes_file_urls_into_platform_safe_local_image_paths() -> None:
    assert normalize_codex_local_image_path("file:///tmp/local-shot.png") == (
        "/tmp/local-shot.png"
    )
    assert (
        normalize_codex_local_image_path(
            "file:///C:/tmp/local-shot.png", "win32"
        )
        == "C:\\tmp\\local-shot.png"
    )
    assert (
        normalize_codex_local_image_path(
            "file://server/share/local-shot.png", "win32"
        )
        == "\\\\server\\share\\local-shot.png"
    )


@pytest.mark.asyncio
async def test_surfaces_codex_spawn_errors_as_regular_model_errors(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    await __shutdown_codex_app_server_for_tests()

    try:
        with pytest.raises(
            RuntimeError,
            match=(
                "failed to start codex app-server"
                "|failed writing to codex app-server stdin"
            ),
        ):
            await call_ai_with_codex_app_server(
                [{"role": "user", "content": "hello"}],
                BASE_MODEL_CONFIG,
                {"resolveImageDetail": resolve_image_detail},
            )
    finally:
        await __shutdown_codex_app_server_for_tests()


@pytest.mark.skip(
    reason=(
        "AbortSignal.reason propagation has no Python equivalent; the port "
        "uses an asyncio.Event abort signal without a reason payload"
    )
)
@pytest.mark.parametrize("label", ["timeout", "user cancellation"])
def test_skips_a_queued_turn_after(label: str) -> None:
    pass


@pytest.mark.asyncio
async def test_counts_queue_waiting_against_each_attempt_timeout_without_sending_expired_turns(
    monkeypatch,
) -> None:
    await __shutdown_codex_app_server_for_tests()
    process = install_fake_process(monkeypatch, hold_turns=True)
    messages = [{"role": "user", "content": "hello"}]
    config = {
        **BASE_MODEL_CONFIG,
        "openaiBaseURL": "codex://app-server",
        "retryInterval": 1,
    }
    chunk_received = asyncio.Event()

    def on_chunk(_chunk: Dict[str, Any]) -> None:
        chunk_received.set()

    first_task = asyncio.create_task(
        call_generative_ai(
            messages,
            get_model_runtime({**config, "timeout": 0, "retryCount": 0}),
            {"stream": True, "onChunk": on_chunk},
        )
    )
    try:
        await asyncio.wait_for(chunk_received.wait(), timeout=5)

        # Queue waiting consumes each attempt's timeout, including attempts
        # that never start a server turn.
        with pytest.raises(RuntimeError, match=r"1 retry \(2/2 attempts\)"):
            await call_generative_ai(
                messages,
                get_model_runtime(
                    {**config, "timeout": 50, "retryCount": 1}
                ),
            )
        assert process.request_log == "thread/start\n"

        process.release_turn()
        await first_task

        # Drain both expired attempts before checking that neither was sent.
        following = await call_generative_ai(
            messages,
            get_model_runtime({**config, "timeout": 5000, "retryCount": 0}),
        )
        assert following["content"] == "hello"
        assert process.request_log == "thread/start\nthread/start\n"
    finally:
        if not first_task.done():
            process.release_turn()
            try:
                await asyncio.wait_for(first_task, timeout=5)
            except (asyncio.TimeoutError, RuntimeError):
                pass
        await __shutdown_codex_app_server_for_tests()


@pytest.mark.skip(
    reason=(
        "the Python provider has no provider-owned turn deadline; model "
        "timeouts are enforced by asyncio.wait_for in call_generative_ai"
    )
)
@pytest.mark.parametrize("timeout", [0, 25])
def test_does_not_create_a_turn_deadline_from_timeout(timeout: int) -> None:
    pass


@pytest.mark.asyncio
async def test_reports_codex_json_rpc_requests_responses_and_turn_notifications(
    monkeypatch,
) -> None:
    install_fake_process(monkeypatch)
    await __shutdown_codex_app_server_for_tests()

    events: List[Dict[str, Any]] = []
    try:
        result = await call_ai_with_codex_app_server(
            [{"role": "user", "content": "hello"}],
            BASE_MODEL_CONFIG,
            {
                "resolveImageDetail": resolve_image_detail,
                "params": {"effort": "max"},
                "onRecordEvent": events.append,
            },
        )

        expected_usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
        }
        assert result["usage"] == expected_usage

        runtime = get_model_runtime(
            {**BASE_MODEL_CONFIG, "openaiBaseURL": "codex://app-server"}
        )
        usage_calls: List[Dict[str, Any]] = []
        runtime.on_usage = usage_calls.append
        chunks: List[Dict[str, Any]] = []
        enriched = await call_generative_ai(
            [{"role": "user", "content": "hello"}],
            runtime,
            {"stream": True, "onChunk": chunks.append},
        )

        assert chunks[-1]["usage"] == expected_usage
        usage = enriched["usage"]
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] == 5
        assert usage["total_tokens"] == 15
        assert usage["cached_input"] == 3
        assert usage["model_name"] == BASE_MODEL_CONFIG["modelName"]
        assert usage["model_description"] == "codex"
        assert usage["slot"] == "default"
        assert usage["request_id"] == "turn-1"
        assert isinstance(usage["_midscene_call_id"], str)
        assert isinstance(usage["time_cost"], (int, float))
        assert usage_calls == [usage]

        assert result["content"] == "hello"
        assert result["protocolMetadata"] == {
            "transport": "json-rpc",
            "threadId": "thread-1",
            "turnId": "turn-1",
            "turnStatus": "completed",
        }

        def has_event(event_type: str, method: str, **extra) -> bool:
            for event in events:
                if event.get("type") != event_type:
                    continue
                protocol = event.get("protocol") or {}
                if protocol.get("method") != method:
                    continue
                matched = True
                for key, value in extra.items():
                    actual = protocol.get(key)
                    if isinstance(value, dict) and isinstance(actual, dict):
                        if not all(
                            actual.get(k) == v for k, v in value.items()
                        ):
                            matched = False
                            break
                    elif actual != value:
                        matched = False
                        break
                if matched:
                    return True
            return False

        assert has_event("request", "thread/start")
        assert has_event(
            "request", "turn/start", params={"effort": "max"}
        )
        assert has_event(
            "chunk",
            "thread/start",
            direction="server",
            result={"thread": {"id": "thread-1"}},
        )
        assert has_event(
            "chunk",
            "turn/start",
            direction="server",
            result={"turn": {"id": "turn-1"}},
        )
        assert has_event("chunk", "item/agentMessage/delta")
        assert has_event("chunk", "turn/completed")
    finally:
        await __shutdown_codex_app_server_for_tests()
