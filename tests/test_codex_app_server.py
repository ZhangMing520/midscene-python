"""Unit tests for the Codex app-server transport.

The tests replace the real ``codex app-server`` child process with an
in-process fake that speaks the same line-delimited JSON-RPC protocol.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

from midscene.core.ai_model.model_adapter.codex_app_server import (
    MIDSCENE_CODEX_APP_SERVER_DEFAULTS,
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
        self._on_message = on_message
        self.closed = False
        self.writes: List[str] = []

    def write(self, data: bytes) -> None:
        text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
        self.writes.append(text)
        for line in text.splitlines():
            if line.strip():
                self._on_message(json.loads(line))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeCodexProcess:
    """A fake ``codex app-server`` process with a canned turn transcript."""

    def __init__(
        self,
        turn_status: str = "completed",
        turn_error: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.stdin = FakeStdin(self._handle_message)
        self.stdout = FakeReader()
        self.stderr = FakeReader()
        self.returncode: Optional[int] = None
        self.received: List[Dict[str, Any]] = []
        self.turn_status = turn_status
        self.turn_error = turn_error
        self._done = asyncio.Event()

    def _reply(self, message: Dict[str, Any], result: Any = None, error: Any = None):
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
            self._reply(message, {"userAgent": "fake-codex"})
        elif method == "thread/start":
            self._reply(message, {"thread": {"id": "thread-1"}})
        elif method == "turn/start":
            self._reply(message, {"turn": {"id": "turn-1"}})
            self._emit_turn_events()
        elif method in ("thread/unsubscribe", "turn/interrupt"):
            self._reply(message, {})
        elif method in ("initialized",):
            return None
        else:
            self._reply(
                message,
                error={"code": -32601, "message": f"unknown method {method}"},
            )
        return None

    def _emit_turn_events(self) -> None:
        self.stdout.feed(
            {
                "method": "item/reasoning/summaryTextDelta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "delta": "thinking...",
                },
            }
        )
        self.stdout.feed(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "delta": "Hello ",
                },
            }
        )
        self.stdout.feed(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "delta": "world",
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
                            "totalTokens": 12,
                            "inputTokens": 7,
                            "cachedInputTokens": 2,
                            "outputTokens": 5,
                            "reasoningOutputTokens": 1,
                        }
                    },
                },
            }
        )
        turn_payload: Dict[str, Any] = {
            "id": "turn-1",
            "status": self.turn_status,
        }
        if self.turn_error is not None:
            turn_payload["error"] = self.turn_error
        self.stdout.feed(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": turn_payload,
                },
            }
        )

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()

    async def wait(self) -> Optional[int]:
        await self._done.wait()
        return self.returncode


def install_fake_process(
    monkeypatch,
    turn_status: str = "completed",
    turn_error: Optional[Dict[str, Any]] = None,
) -> FakeCodexProcess:
    process = FakeCodexProcess(turn_status=turn_status, turn_error=turn_error)

    async def fake_spawn():
        return process

    monkeypatch.setattr(codex_module, "_spawn_codex_app_server", fake_spawn)
    return process


def methods_received(process: FakeCodexProcess) -> List[str]:
    return [message.get("method") for message in process.received]


def test_is_codex_app_server_provider() -> None:
    assert is_codex_app_server_provider("codex://local")
    assert is_codex_app_server_provider("  CODEX://local  ")
    assert not is_codex_app_server_provider("https://api.openai.com/v1")
    assert not is_codex_app_server_provider(None)


def test_normalize_codex_local_image_path() -> None:
    assert normalize_codex_local_image_path("file:///tmp/shot.png") == "/tmp/shot.png"
    assert normalize_codex_local_image_path("/tmp/shot.png") == "/tmp/shot.png"
    assert (
        normalize_codex_local_image_path("file:///tmp/a%20b.png") == "/tmp/a b.png"
    )
    assert (
        normalize_codex_local_image_path("file://server/share/shot.png", "linux")
        == "//server/share/shot.png"
    )
    assert (
        normalize_codex_local_image_path("file:///C:/shots/a.png", "win32")
        == "C:\\shots\\a.png"
    )
    assert (
        normalize_codex_local_image_path("file://server/share/a.png", "win32")
        == "\\\\server\\share\\a.png"
    )


def test_build_codex_turn_payload_from_messages() -> None:
    messages = [
        {"role": "system", "content": "You are a testing assistant."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this screenshot"},
                {"type": "image", "url": "data:image/png;base64,AAAA"},
                {"type": "image", "url": "/tmp/shot.png", "detail": "low"},
                {"type": "image", "url": "file:///tmp/other.png"},
            ],
        },
    ]

    payload = build_codex_turn_payload_from_messages(messages)

    assert payload["developerInstructions"] == "You are a testing assistant."
    inputs = payload["input"]
    assert inputs[0] == {
        "type": "text",
        "text": "[USER]\nDescribe this screenshot",
        "text_elements": [],
    }
    assert inputs[1] == {
        "type": "image",
        "url": "data:image/png;base64,AAAA",
        "detail": "high",
    }
    assert inputs[2] == {"type": "localImage", "path": "/tmp/shot.png", "detail": "low"}
    assert inputs[3] == {
        "type": "localImage",
        "path": "/tmp/other.png",
        "detail": "high",
    }


def test_build_default_codex_app_server_params() -> None:
    assert build_default_codex_app_server_params({}) == {
        "config": dict(MIDSCENE_CODEX_APP_SERVER_DEFAULTS)
    }
    assert build_default_codex_app_server_params(
        {"userConfig": {"reasoningEnabled": True, "reasoningEffort": "HIGH"}}
    ) == {"config": {"effort": "high"}}
    assert build_default_codex_app_server_params(
        {"userConfig": {"reasoningEnabled": True, "reasoningEffort": "bogus"}}
    ) == {"config": {"effort": "medium"}}


@pytest.mark.asyncio
async def test_initialize_and_streaming_turn(monkeypatch) -> None:
    process = install_fake_process(monkeypatch)
    chunks: List[Dict[str, Any]] = []

    try:
        result = await call_ai_with_codex_app_server(
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hello"},
            ],
            {"modelName": "gpt-5-codex"},
            {
                "stream": True,
                "on_chunk": chunks.append,
                "params": {"effort": "medium"},
            },
        )
    finally:
        await __shutdown_codex_app_server_for_tests()

    assert result["content"] == "Hello world"
    assert result["reasoning_content"] == "thinking..."
    assert result["isStreamed"] is True
    assert result["protocolMetadata"] == {
        "transport": "json-rpc",
        "threadId": "thread-1",
        "turnId": "turn-1",
        "turnStatus": "completed",
    }
    assert result["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }

    received = methods_received(process)
    assert received[:4] == ["initialize", "initialized", "thread/start", "turn/start"]
    assert "thread/unsubscribe" in received

    thread_start = next(m for m in process.received if m.get("method") == "thread/start")
    assert thread_start["params"]["model"] == "gpt-5-codex"
    assert thread_start["params"]["approvalPolicy"] == "never"
    assert thread_start["params"]["sandbox"] == "read-only"
    assert thread_start["params"]["developerInstructions"] == "system prompt"

    turn_start = next(m for m in process.received if m.get("method") == "turn/start")
    assert turn_start["params"]["threadId"] == "thread-1"
    assert turn_start["params"]["effort"] == "medium"
    assert turn_start["params"]["input"][0]["text"] == "[USER]\nhello"

    assert [chunk["content"] for chunk in chunks] == ["", "Hello ", "world", ""]
    assert chunks[1]["accumulated"] == "Hello "
    assert chunks[-1]["isComplete"] is True
    assert chunks[-1]["usage"]["total_tokens"] == 12

    assert process.returncode is not None
    assert process.stdin.closed is True


@pytest.mark.asyncio
async def test_call_generative_ai_routes_codex_provider(monkeypatch) -> None:
    process = install_fake_process(monkeypatch)
    runtime = get_model_runtime(
        {
            "openaiBaseURL": "codex://local",
            "modelName": "gpt-5-codex",
            "modelFamily": "gpt-5",
            "retryCount": 0,
            "timeout": 5000,
        }
    )

    try:
        result = await call_generative_ai(
            [{"role": "user", "content": "hello"}], runtime
        )
    finally:
        await __shutdown_codex_app_server_for_tests()

    assert result["content"] == "Hello world"
    assert result["reasoningContent"] == "thinking..."
    assert result["requestId"] == "turn-1"
    assert result["rawUsage"]["total_tokens"] == 12
    assert result["usage"]["total_tokens"] == 12
    assert result["usage"]["request_id"] == "turn-1"

    turn_start = next(m for m in process.received if m.get("method") == "turn/start")
    # gpt-5 has no Python-specific override, so the default builder is used.
    assert turn_start["params"]["effort"] == "none"


@pytest.mark.asyncio
async def test_turn_error_is_raised(monkeypatch) -> None:
    install_fake_process(
        monkeypatch, turn_status="failed", turn_error={"message": "boom"}
    )

    try:
        with pytest.raises(RuntimeError, match="boom"):
            await call_ai_with_codex_app_server(
                [{"role": "user", "content": "hello"}],
                {"modelName": "gpt-5-codex"},
            )
    finally:
        await __shutdown_codex_app_server_for_tests()
