"""Codex app-server JSON-RPC transport (upstream codex/codex-app-server.ts).

The provider spawns ``codex app-server`` and speaks line-delimited JSON-RPC over
its stdin/stdout. This module ports the initialize handshake, thread creation,
turn start, streaming notifications, token usage mapping, thread unsubscribe,
turn interrupt and process cleanup.

Approximations relative to the TypeScript implementation:

* Abort signalling accepts ``asyncio.Event``-like objects (``is_set()`` or an
  ``aborted`` attribute) instead of a browser ``AbortSignal``.
* ``onRecordEvent`` keeps the upstream direction/method payload shape; the
  Python recorder only stores the event dictionaries as-is.
* The Node.js event-loop ``unref`` behaviour has no Python equivalent; reader
  tasks are cancelled during :meth:`CodexAppServerConnection.dispose` instead.
"""

from typing import Any, Callable, Dict, List, Optional
import asyncio
import inspect
import json
import os
import re
import sys
import time
from urllib.parse import unquote, urlsplit

from loguru import logger

CODEX_PROVIDER_SCHEME = "codex://"
CODEX_INTERRUPT_TIMEOUT_MS = 5_000
CODEX_DEFAULT_PROCESS_START_TIMEOUT_MS = 15 * 1000
CODEX_DEFAULT_CLEANUP_TIMEOUT_MS = 8 * 1000
CODEX_TEXT_INPUT_MAX_LENGTH = 256 * 1024


def _to_non_empty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def is_codex_app_server_provider(base_url: Optional[str]) -> bool:
    """Whether ``base_url`` selects the Codex app-server transport."""
    if not isinstance(base_url, str):
        return False
    return base_url.strip().lower().startswith(CODEX_PROVIDER_SCHEME)


def normalize_codex_local_image_path(
    image_url: str, platform: Optional[str] = None
) -> str:
    """Convert a ``file://`` URL to a native path Codex can read."""
    if not image_url.startswith("file://"):
        return image_url

    platform = platform or sys.platform
    try:
        parsed = urlsplit(image_url)
        pathname = unquote(parsed.path)
        host = (parsed.hostname or "").lower()

        if platform == "win32":
            windows_path = pathname.replace("/", "\\")
            windows_path = re.sub(r"^\\([A-Za-z]:)", r"\1", windows_path)
            if host and host != "localhost":
                return f"\\\\{parsed.hostname}{windows_path}"
            return windows_path

        if host and host != "localhost":
            return f"//{parsed.hostname}{pathname}"
        return pathname
    except Exception:
        return unquote(image_url[len("file://") :])


def _default_resolve_image_detail(input_data: Dict[str, Any]) -> str:
    return input_data.get("imageDetail") or "high"


def _extract_text_from_message(message: Dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _extract_image_inputs(
    message: Dict[str, Any],
    resolve_image_detail: Callable[[Dict[str, Any]], str],
) -> List[Dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []

    inputs: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "image":
            continue
        image_url = _to_non_empty_string(part.get("url"))
        detail = resolve_image_detail({"imageDetail": part.get("detail")})
        if not image_url:
            continue

        if image_url.startswith(("/", "./", "../", "file://")):
            path = (
                normalize_codex_local_image_path(image_url)
                if image_url.startswith("file://")
                else image_url
            )
            inputs.append({"type": "localImage", "path": path, "detail": detail})
            continue

        inputs.append({"type": "image", "url": image_url, "detail": detail})
    return inputs


def _message_from_entry(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("Unsupported Codex conversation entry")
    if "role" in entry:
        return entry
    if entry.get("type") == "input-message":
        message = entry.get("message")
        return message if isinstance(message, dict) else {}
    output = entry.get("output")
    if not isinstance(output, dict) or output.get("type") != "chat-completion":
        raise ValueError("Cannot replay Responses output in a Codex conversation")
    raw_value = output.get("rawValue")
    content = raw_value.get("content") if isinstance(raw_value, dict) else None
    return {"role": "assistant", "content": content or ""}


def build_codex_turn_payload_from_messages(
    messages: List[Dict[str, Any]],
    resolve_image_detail: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    """Build the ``developerInstructions`` + ``input`` payload for a turn."""
    resolver = resolve_image_detail or _default_resolve_image_detail
    developer_instruction_parts: List[str] = []
    transcript_parts: List[str] = []
    image_inputs: List[Dict[str, Any]] = []

    for entry in messages or []:
        message = _message_from_entry(entry)
        role = message.get("role") or ""
        text = _extract_text_from_message(message)

        if role == "system":
            if text.strip():
                developer_instruction_parts.append(text.strip())
            continue

        role_tag = role.upper()
        if text.strip():
            transcript_parts.append(f"[{role_tag}]\n{text.strip()}")
        else:
            transcript_parts.append(f"[{role_tag}]\n(no text content)")

        if role == "user":
            image_inputs.extend(_extract_image_inputs(message, resolver))

    full_transcript = "\n\n".join(transcript_parts)
    if len(full_transcript) > CODEX_TEXT_INPUT_MAX_LENGTH:
        full_transcript = full_transcript[-CODEX_TEXT_INPUT_MAX_LENGTH:]
    transcript_text = full_transcript or "Please answer the latest user request."

    inputs: List[Dict[str, Any]] = [
        {"type": "text", "text": transcript_text, "text_elements": []},
        *image_inputs,
    ]

    developer_instructions = (
        "\n\n".join(developer_instruction_parts) if developer_instruction_parts else None
    )
    return {
        "developerInstructions": developer_instructions,
        "input": inputs,
    }


class CodexAppServerAbortError(RuntimeError):
    """Raised when the caller aborts a Codex app-server request."""


def _throw_if_aborted(abort_signal: Any) -> None:
    if abort_signal is None:
        return
    is_set = getattr(abort_signal, "is_set", None)
    if callable(is_set) and is_set():
        raise CodexAppServerAbortError("codex app-server request aborted")
    if getattr(abort_signal, "aborted", False):
        raise CodexAppServerAbortError("codex app-server request aborted")


def _is_abort_error(error: BaseException) -> bool:
    if isinstance(error, asyncio.CancelledError):
        return True
    if isinstance(error, CodexAppServerAbortError):
        return True
    return "abort" in str(error).lower()


async def _spawn_codex_app_server() -> Any:
    """Spawn ``codex app-server``; tests monkeypatch this seam."""
    return await asyncio.create_subprocess_exec(
        "codex",
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _config_get(model_config: Any, key: str) -> Any:
    if isinstance(model_config, dict):
        return model_config.get(key)
    return getattr(model_config, key, None)


class CodexAppServerConnection:
    """A long-lived line-delimited JSON-RPC connection to ``codex app-server``."""

    def __init__(self, process: Any):
        self._process = process
        self._message_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._pending_messages: List[Dict[str, Any]] = []
        self._next_request_id = 1
        self._closed = False
        self._disposed = False
        self._last_exit_code: Optional[int] = None
        self._process_error_message: Optional[str] = None
        self._stderr_buffer = ""
        self._tasks: List["asyncio.Task[Any]"] = []

    @classmethod
    async def create(cls, process: Any = None) -> "CodexAppServerConnection":
        if process is None:
            try:
                process = await _spawn_codex_app_server()
            except FileNotFoundError as error:
                raise RuntimeError(
                    "failed to start codex app-server: codex binary not found"
                ) from error
            except OSError as error:
                raise RuntimeError(
                    f"failed to start codex app-server: {error}"
                ) from error

        if (
            getattr(process, "stdin", None) is None
            or getattr(process, "stdout", None) is None
            or getattr(process, "stderr", None) is None
        ):
            raise RuntimeError("failed to start codex app-server: stdio unavailable")

        connection = cls(process)
        connection._attach_process_listeners()
        await connection._initialize_handshake()
        return connection

    def is_closed(self) -> bool:
        return self._closed

    async def run_turn(
        self,
        messages: List[Dict[str, Any]],
        resolve_image_detail: Optional[Callable[[Dict[str, Any]], str]] = None,
        model_config: Any = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[Dict[str, Any]], Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        abort_signal: Any = None,
        on_record_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Start a thread + turn and stream notifications until completion."""
        is_streaming = bool(stream and on_chunk)

        payload = build_codex_turn_payload_from_messages(
            messages, resolve_image_detail
        )
        developer_instructions = payload["developerInstructions"]
        inputs = payload["input"]

        thread_id: Optional[str] = None
        turn_id: Optional[str] = None
        latest_error_message: Optional[str] = None
        accumulated_text = ""
        accumulated_reasoning = ""
        latest_usage: Optional[Dict[str, Any]] = None

        def record(event: Dict[str, Any]) -> None:
            if on_record_event is None:
                return
            result = on_record_event(event)
            if inspect.isawaitable(result):
                # Record callbacks are synchronous upstream; run coroutines when given.
                asyncio.ensure_future(result)

        async def emit_chunk(
            content: str,
            reasoning: str,
            is_complete: bool,
            usage: Optional[Dict[str, Any]] = None,
        ) -> None:
            if not is_streaming or on_chunk is None:
                return
            chunk = {
                "content": content,
                "reasoning_content": reasoning,
                "accumulated": accumulated_text,
                "isComplete": is_complete,
                "usage": usage,
            }
            result = on_chunk(chunk)
            if inspect.isawaitable(result):
                await result

        try:
            thread_start_params = {
                "model": _config_get(model_config, "modelName"),
                "cwd": os.getcwd(),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "experimentalRawEvents": False,
                "persistExtendedHistory": False,
                "developerInstructions": developer_instructions or None,
            }
            record(
                {
                    "type": "request",
                    "protocol": {
                        "direction": "client",
                        "method": "thread/start",
                        "params": thread_start_params,
                    },
                }
            )
            thread_start_response = await self._request(
                "thread/start", thread_start_params, abort_signal=abort_signal
            )
            record(
                {
                    "type": "chunk",
                    "protocol": {
                        "direction": "server",
                        "method": "thread/start",
                        "result": thread_start_response,
                    },
                }
            )

            thread_id = ((thread_start_response or {}).get("thread") or {}).get("id")
            if not thread_id:
                raise RuntimeError("thread/start did not return a thread id")

            turn_start_params = {**(params or {}), "threadId": thread_id, "input": inputs}
            record(
                {
                    "type": "request",
                    "protocol": {
                        "direction": "client",
                        "method": "turn/start",
                        "params": turn_start_params,
                    },
                }
            )
            turn_start_response = await self._request(
                "turn/start", turn_start_params, abort_signal=abort_signal
            )
            record(
                {
                    "type": "chunk",
                    "protocol": {
                        "direction": "server",
                        "method": "turn/start",
                        "result": turn_start_response,
                    },
                }
            )

            turn_id = ((turn_start_response or {}).get("turn") or {}).get("id")
            if not turn_id:
                raise RuntimeError("turn/start did not return a turn id")

            turn_status: Optional[str] = None
            while not turn_status:
                message = await self._next_message(abort_signal=abort_signal)

                if self._is_response_message(message):
                    # No concurrent requests in the adapter runtime.
                    continue

                if self._is_request_message(message):
                    await self._respond_to_server_request(message)
                    continue

                method = message.get("method")
                notification_params = message.get("params") or {}
                if not isinstance(notification_params, dict):
                    notification_params = {}

                belongs_to_current_turn = (
                    notification_params.get("threadId") == thread_id
                    and (
                        notification_params.get("turnId") == turn_id
                        or (notification_params.get("turn") or {}).get("id") == turn_id
                    )
                )

                if belongs_to_current_turn:
                    record(
                        {
                            "type": "chunk",
                            "protocol": {
                                "direction": "server",
                                "method": method,
                                "params": notification_params,
                            },
                        }
                    )

                if method == "error":
                    error_info = notification_params.get("error") or {}
                    message_text = (
                        error_info.get("message")
                        if isinstance(error_info, dict)
                        else None
                    ) or notification_params.get(
                        "message"
                    ) or "codex app-server reported turn error"
                    latest_error_message = str(message_text)
                    continue

                if (
                    method == "item/agentMessage/delta"
                    and notification_params.get("threadId") == thread_id
                    and notification_params.get("turnId") == turn_id
                ):
                    delta = str(notification_params.get("delta") or "")
                    if delta:
                        accumulated_text += delta
                        await emit_chunk(delta, "", False)
                    continue

                if (
                    method
                    in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta")
                    and notification_params.get("threadId") == thread_id
                    and notification_params.get("turnId") == turn_id
                ):
                    delta = str(notification_params.get("delta") or "")
                    if delta:
                        accumulated_reasoning += delta
                        await emit_chunk("", delta, False)
                    continue

                item = notification_params.get("item") or {}
                if (
                    method == "item/completed"
                    and notification_params.get("threadId") == thread_id
                    and notification_params.get("turnId") == turn_id
                    and isinstance(item, dict)
                    and item.get("type") == "agentMessage"
                    and isinstance(item.get("text"), str)
                    and not accumulated_text
                ):
                    accumulated_text = item["text"]
                    continue

                if (
                    method == "thread/tokenUsage/updated"
                    and notification_params.get("threadId") == thread_id
                    and notification_params.get("turnId") == turn_id
                ):
                    latest_usage = self._map_usage(notification_params)
                    continue

                turn = notification_params.get("turn") or {}
                if (
                    method == "turn/completed"
                    and notification_params.get("threadId") == thread_id
                    and isinstance(turn, dict)
                    and turn.get("id") == turn_id
                ):
                    turn_status = str(turn.get("status") or "")
                    turn_error = turn.get("error")
                    turn_error_message = (
                        turn_error.get("message")
                        if isinstance(turn_error, dict)
                        else None
                    )
                    latest_error_message = (
                        turn_error_message or latest_error_message or None
                    )
                    break

            if turn_status != "completed":
                raise RuntimeError(
                    latest_error_message
                    or f'codex turn finished with status "{turn_status or "unknown"}"'
                )

            if is_streaming:
                await emit_chunk("", "", True, latest_usage)

            return {
                "content": accumulated_text,
                "reasoning_content": accumulated_reasoning or None,
                "usage": latest_usage,
                "isStreamed": is_streaming,
                "protocolMetadata": {
                    "transport": "json-rpc",
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "turnStatus": turn_status,
                },
            }
        except BaseException as error:
            if _is_abort_error(error) and thread_id and turn_id:
                try:
                    await self._request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                        deadline_at=time.monotonic()
                        + CODEX_INTERRUPT_TIMEOUT_MS / 1000,
                    )
                except Exception:
                    pass
            raise
        finally:
            if thread_id:
                try:
                    await self._request(
                        "thread/unsubscribe",
                        {"threadId": thread_id},
                        deadline_at=time.monotonic()
                        + CODEX_DEFAULT_CLEANUP_TIMEOUT_MS / 1000,
                    )
                except Exception as error:
                    logger.warning(
                        f"failed to unsubscribe codex thread {thread_id}: {error}"
                    )

    async def dispose(self) -> None:
        """Close stdin, kill the child process and stop reader tasks."""
        if self._disposed:
            return
        self._closed = True
        self._disposed = True

        stdin = getattr(self._process, "stdin", None)
        if stdin is not None:
            try:
                stdin.close()
            except Exception:
                pass
            wait_closed = getattr(stdin, "wait_closed", None)
            if callable(wait_closed):
                try:
                    result = wait_closed()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    pass

        if getattr(self._process, "returncode", None) is None:
            try:
                self._process.kill()
            except Exception:
                pass

        try:
            await asyncio.wait_for(self._process.wait(), timeout=1.0)
        except Exception:
            pass

        for task in self._tasks:
            task.cancel()
        self._tasks = []

    def _attach_process_listeners(self) -> None:
        self._tasks.append(asyncio.ensure_future(self._read_stdout()))
        self._tasks.append(asyncio.ensure_future(self._read_stderr()))
        self._tasks.append(asyncio.ensure_future(self._watch_exit()))

    async def _read_stdout(self) -> None:
        stream = self._process.stdout
        while True:
            try:
                line = await stream.readline()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._process_error_message = str(error)
                self._closed = True
                return
            if not line:
                return
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
            for raw_line in text.splitlines():
                trimmed = raw_line.strip()
                if not trimmed:
                    continue
                try:
                    parsed = json.loads(trimmed)
                except json.JSONDecodeError:
                    logger.warning(
                        f"ignored non-JSON message from codex app-server: {trimmed}"
                    )
                    continue
                if isinstance(parsed, dict):
                    self._message_queue.put_nowait(parsed)

    async def _read_stderr(self) -> None:
        stream = self._process.stderr
        while True:
            try:
                line = await stream.readline()
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            if not line:
                return
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
            self._stderr_buffer += text
            if len(self._stderr_buffer) > 8192:
                self._stderr_buffer = self._stderr_buffer[-8192:]

    async def _watch_exit(self) -> None:
        wait = getattr(self._process, "wait", None)
        if not callable(wait):
            return
        try:
            exit_code = await wait()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._closed = True
            self._process_error_message = str(error)
            return
        self._closed = True
        self._last_exit_code = exit_code

    async def _initialize_handshake(self) -> None:
        deadline_at = time.monotonic() + CODEX_DEFAULT_PROCESS_START_TIMEOUT_MS / 1000
        await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "midscene_codex_provider",
                    "title": "Midscene Codex Provider",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": False},
            },
            deadline_at=deadline_at,
        )
        await self._send_message({"method": "initialized"})

    @staticmethod
    def _map_usage(usage: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        token_usage = usage.get("tokenUsage") or {}
        picked = token_usage.get("last") or token_usage.get("total")
        if not isinstance(picked, dict):
            return None
        return {
            "prompt_tokens": picked.get("inputTokens") or 0,
            "completion_tokens": picked.get("outputTokens") or 0,
            "total_tokens": picked.get("totalTokens") or 0,
            "prompt_tokens_details": {
                "cached_tokens": picked.get("cachedInputTokens") or 0
            },
            "completion_tokens_details": {
                "reasoning_tokens": picked.get("reasoningOutputTokens") or 0
            },
        }

    @staticmethod
    def _is_request_message(message: Dict[str, Any]) -> bool:
        return isinstance(message.get("method"), str) and message.get("id") is not None

    @staticmethod
    def _is_response_message(message: Dict[str, Any]) -> bool:
        return (
            message.get("id") is not None
            and ("result" in message or "error" in message)
            and not isinstance(message.get("method"), str)
        )

    async def _request(
        self,
        method: str,
        params: Any = None,
        deadline_at: Optional[float] = None,
        abort_signal: Any = None,
    ) -> Any:
        _throw_if_aborted(abort_signal)
        request_id = self._next_request_id
        self._next_request_id += 1

        await self._send_message({"id": request_id, "method": method, "params": params})

        while True:
            message = await self._next_message(
                deadline_at=deadline_at,
                abort_signal=abort_signal,
                include_pending=False,
            )

            if self._is_response_message(message) and message.get("id") == request_id:
                error = message.get("error")
                if error:
                    error_message = (
                        error.get("message")
                        if isinstance(error, dict)
                        else str(error)
                    )
                    raise RuntimeError(
                        f"codex app-server {method} failed: "
                        f"{error_message or 'unknown error'}"
                    )
                return message.get("result") or {}

            if self._is_request_message(message):
                await self._respond_to_server_request(message)
                continue

            # Keep unmatched notifications/other responses for later stream handling.
            self._pending_messages.append(message)

    async def _respond_to_server_request(self, request: Dict[str, Any]) -> None:
        request_id = request.get("id")
        method = request.get("method")

        if method == "item/commandExecution/requestApproval":
            result: Any = {"decision": "decline"}
        elif method == "item/fileChange/requestApproval":
            result = {"decision": "decline"}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "cancel", "content": None}
        elif method == "item/tool/requestUserInput":
            result = {"answers": []}
        else:
            await self._send_message(
                {
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"unsupported server request: {method}",
                    },
                }
            )
            return

        await self._send_message({"id": request_id, "result": result})

    async def _next_message(
        self,
        deadline_at: Optional[float] = None,
        abort_signal: Any = None,
        include_pending: bool = True,
    ) -> Dict[str, Any]:
        if include_pending and self._pending_messages:
            return self._pending_messages.pop(0)

        while True:
            _throw_if_aborted(abort_signal)

            if deadline_at is not None and time.monotonic() > deadline_at:
                raise RuntimeError("codex app-server request timed out")

            if not self._message_queue.empty():
                return self._message_queue.get_nowait()

            if self._closed:
                raise self._create_closed_connection_error()

            try:
                return await asyncio.wait_for(self._message_queue.get(), timeout=0.02)
            except asyncio.TimeoutError:
                continue

    async def _send_message(self, payload: Dict[str, Any]) -> None:
        if self._closed:
            raise self._create_closed_connection_error()

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(line.encode("utf-8"))
            drain = getattr(self._process.stdin, "drain", None)
            if callable(drain):
                result = drain()
                if inspect.isawaitable(result):
                    await result
        except Exception as error:
            raise RuntimeError(
                f"failed writing to codex app-server stdin: {error}"
            ) from error

    def _create_closed_connection_error(self) -> RuntimeError:
        stderr = self._stderr_buffer.strip()
        if self._process_error_message:
            suffix = f". stderr={stderr}" if stderr else ""
            return RuntimeError(
                f"codex app-server process error: "
                f"{self._process_error_message}{suffix}"
            )
        suffix = f". stderr={stderr}" if stderr else ""
        return RuntimeError(
            "codex app-server connection closed "
            f"(exitCode={self._last_exit_code}){suffix}"
        )


class CodexAppServerConnectionManager:
    """Serialize turns and keep one long-lived app-server connection."""

    def __init__(self) -> None:
        self._connection: Optional[CodexAppServerConnection] = None
        self._lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # pytest-asyncio may supply a new loop per test; drop stale bindings.
            self._loop = loop
            self._connection = None
            self._lock = asyncio.Lock()
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def run_turn(
        self,
        messages: List[Dict[str, Any]],
        resolve_image_detail: Optional[Callable[[Dict[str, Any]], str]] = None,
        model_config: Any = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[Dict[str, Any]], Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        abort_signal: Any = None,
        on_record_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        async with self._get_lock():
            _throw_if_aborted(abort_signal)
            connection = await self._get_connection()
            _throw_if_aborted(abort_signal)
            try:
                return await connection.run_turn(
                    messages=messages,
                    resolve_image_detail=resolve_image_detail,
                    model_config=model_config,
                    stream=stream,
                    on_chunk=on_chunk,
                    params=params,
                    abort_signal=abort_signal,
                    on_record_event=on_record_event,
                )
            except BaseException as error:
                if connection.is_closed() or not _is_abort_error(error):
                    await self._reset_connection()
                raise

    async def shutdown_for_tests(self) -> None:
        await self._reset_connection()

    async def _get_connection(self) -> CodexAppServerConnection:
        if self._connection is None or self._connection.is_closed():
            self._connection = await CodexAppServerConnection.create()
        return self._connection

    async def _reset_connection(self) -> None:
        if self._connection is None:
            return
        stale_connection = self._connection
        self._connection = None
        await stale_connection.dispose()


codex_connection_manager = CodexAppServerConnectionManager()


async def call_ai_with_codex_app_server(
    messages: List[Dict[str, Any]],
    model_config: Any,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one Codex turn through the shared app-server connection."""
    options = options or {}
    return await codex_connection_manager.run_turn(
        messages=messages,
        model_config=model_config,
        resolve_image_detail=options.get("resolve_image_detail")
        or options.get("resolveImageDetail"),
        stream=options.get("stream"),
        on_chunk=options.get("onChunk") or options.get("on_chunk"),
        params=options.get("params"),
        abort_signal=options.get("abort_signal") or options.get("abortSignal"),
        on_record_event=options.get("on_record_event")
        or options.get("onRecordEvent"),
    )


async def __shutdown_codex_app_server_for_tests() -> None:
    await codex_connection_manager.shutdown_for_tests()


__all__ = [
    "CODEX_PROVIDER_SCHEME",
    "CodexAppServerAbortError",
    "CodexAppServerConnection",
    "CodexAppServerConnectionManager",
    "build_codex_turn_payload_from_messages",
    "call_ai_with_codex_app_server",
    "codex_connection_manager",
    "is_codex_app_server_provider",
    "normalize_codex_local_image_path",
]
