"""RDP backend clients (upstream backend-client.ts).

Two transports are available:

* ``UnsupportedRDPBackendClient`` keeps the upstream not-implemented
  behaviour for callers that do not want a helper process.
* ``HelperProcessRDPBackendClient`` spawns the per-platform ``rdp-helper``
  binary and speaks the newline-delimited JSON protocol from ``protocol.py``.
"""

import asyncio
import inspect
import json
from typing import Any, Callable, Dict, Optional, Tuple

from loguru import logger

from midscene.computer.rdp.address import normalize_rdp_connection_config
from midscene.computer.rdp.helper_binary import get_rdp_helper_binary_path
from midscene.computer.rdp.protocol import (
    RDPBackendClient,
    RDPConnectionConfig,
    RDPConnectionInfo,
)

HELPER_SHUTDOWN_TIMEOUT_S = 3.0
HELPER_WRITE_ERROR_DIAGNOSTIC_DELAY_S = 0.05
MAX_STDERR_CHARS = 16_384

SpawnFn = Callable[[str], Any]


def _not_implemented() -> RuntimeError:
    return RuntimeError(
        "RDP backend transport is not implemented yet. Inject a custom "
        "backend into RDPDevice or implement a real helper transport."
    )


class UnsupportedRDPBackendClient:
    """Default backend: the helper transport is not implemented (upstream)."""

    async def connect(self, config: RDPConnectionConfig) -> RDPConnectionInfo:
        raise _not_implemented()

    async def disconnect(self) -> None:
        raise _not_implemented()

    async def screenshot_base64(self) -> str:
        raise _not_implemented()

    async def size(self):
        raise _not_implemented()

    async def mouse_move(self, x: int, y: int) -> None:
        raise _not_implemented()

    async def mouse_button(self, button, action) -> None:
        raise _not_implemented()

    async def wheel(self, direction, amount, x=None, y=None) -> None:
        raise _not_implemented()

    async def key_press(self, key_name: str) -> None:
        raise _not_implemented()

    async def type_text(self, text: str) -> None:
        raise _not_implemented()

    async def clear_input(self) -> None:
        raise _not_implemented()


class _HelperDiagnostics:
    def __init__(self, path: str, pid: Optional[int]):
        self.path = path
        self.pid = pid
        self.exit_code: Optional[int] = None
        self.exit_signal: Optional[str] = None
        self.stderr_buffer = ""

    def capture_stderr(self, text: str) -> None:
        if not text.strip():
            return
        logger.debug(
            f"rdp helper stderr path={self.path} pid={self.pid} "
            f"stderr={text.strip()}"
        )
        self.stderr_buffer += text
        if len(self.stderr_buffer) > MAX_STDERR_CHARS:
            self.stderr_buffer = self.stderr_buffer[-MAX_STDERR_CHARS:]


class HelperProcessRDPBackendClient:
    """RDP backend that drives the bundled ``rdp-helper`` process."""

    def __init__(
        self,
        options: Optional[Dict[str, Any]] = None,
        spawn_fn: Optional[SpawnFn] = None,
        helper_path: Optional[str] = None,
    ):
        options = options or {}
        self._spawn_fn: Optional[SpawnFn] = spawn_fn or options.get("spawnFn")
        override_path = helper_path or options.get("helperPath")
        self._resolve_helper_path = override_path
        self._child: Any = None
        self._connected = False
        self._fatal_helper_error: Optional[BaseException] = None
        self._pending: Dict[str, Tuple[asyncio.Future, Any]] = {}
        self._diagnostics: Dict[int, _HelperDiagnostics] = {}
        self._reader_tasks: list = []
        self._next_request_id = 0
        self._spawn_lock: Optional[asyncio.Lock] = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self, config: RDPConnectionConfig) -> RDPConnectionInfo:
        self._fatal_helper_error = None
        response = await self._send(
            {
                "type": "connect",
                "config": normalize_rdp_connection_config(config),
            }
        )
        if response.get("type") != "connected":
            raise RuntimeError(
                f"Expected connected response, got {response.get('type')}"
            )
        self._connected = True
        self._fatal_helper_error = None
        return response.get("info", {})

    async def disconnect(self) -> None:
        child = self._child
        if child is None:
            return

        disconnect_error: Optional[BaseException] = None
        if self._connected and child.returncode is None:
            try:
                response = await self._send({"type": "disconnect"})
                self._expect_ok(response, "disconnect")
            except BaseException as error:  # noqa: BLE001 - preserved below
                disconnect_error = error

        self._connected = False
        self._fatal_helper_error = None
        await self._shutdown_helper()

        if disconnect_error is not None and not _is_shutdown_error(
            disconnect_error
        ):
            raise disconnect_error

    async def screenshot_base64(self) -> str:
        response = await self._send({"type": "screenshot"})
        if response.get("type") != "screenshot":
            raise RuntimeError(
                f"Expected screenshot response, got {response.get('type')}"
            )
        return response.get("base64", "")

    async def size(self):
        response = await self._send({"type": "size"})
        if response.get("type") != "size":
            raise RuntimeError(f"Expected size response, got {response.get('type')}")
        return response.get("size", {})

    async def mouse_move(self, x: int, y: int) -> None:
        self._expect_ok(
            await self._send({"type": "mouseMove", "x": x, "y": y}),
            "mouseMove",
        )

    async def mouse_button(self, button, action) -> None:
        self._expect_ok(
            await self._send(
                {"type": "mouseButton", "button": button, "action": action}
            ),
            "mouseButton",
        )

    async def wheel(self, direction, amount, x=None, y=None) -> None:
        self._expect_ok(
            await self._send(
                {
                    "type": "wheel",
                    "direction": direction,
                    "amount": amount,
                    "x": x,
                    "y": y,
                }
            ),
            "wheel",
        )

    async def key_press(self, key_name: str) -> None:
        self._expect_ok(
            await self._send({"type": "keyPress", "keyName": key_name}),
            "keyPress",
        )

    async def type_text(self, text: str) -> None:
        self._expect_ok(
            await self._send({"type": "typeText", "text": text}),
            "typeText",
        )

    async def clear_input(self) -> None:
        self._expect_ok(
            await self._send({"type": "clearInput"}),
            "clearInput",
        )

    # -- helper process ----------------------------------------------------

    async def _ensure_helper_started(self):
        if self._child is not None and self._child.returncode is None:
            return self._child
        if self._spawn_lock is None:
            self._spawn_lock = asyncio.Lock()
        async with self._spawn_lock:
            if self._child is not None and self._child.returncode is None:
                return self._child
            helper_path = (
                self._resolve_helper_path
                if self._resolve_helper_path
                else get_rdp_helper_binary_path()
            )
            logger.debug(f"starting rdp helper path={helper_path}")
            if self._spawn_fn is not None:
                child = self._spawn_fn(helper_path)
                if inspect.isawaitable(child):
                    child = await child
            else:
                child = await asyncio.create_subprocess_exec(
                    helper_path,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            self._child = child
            diagnostics = _HelperDiagnostics(helper_path, getattr(child, "pid", None))
            self._diagnostics[id(child)] = diagnostics
            logger.debug(
                f"started rdp helper path={helper_path} pid={diagnostics.pid}"
            )
            self._reader_tasks = [
                asyncio.ensure_future(self._read_stdout(child, diagnostics)),
                asyncio.ensure_future(self._read_stderr(child, diagnostics)),
                asyncio.ensure_future(self._watch_exit(child, diagnostics)),
            ]
            return child

    async def _read_stdout(self, child, diagnostics):
        stdout = child.stdout
        while True:
            line = await stdout.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except ValueError:
                protocol_error = self._create_helper_error(
                    f"RDP helper emitted malformed JSON: {text}",
                    None,
                    diagnostics,
                )
                self._reject_pending_for_child(child, protocol_error)
                if self._child is child:
                    await self._shutdown_helper(protocol_error)
                return

            request_id = parsed.get("id")
            pending = self._pending.pop(request_id, None)
            if pending is None:
                logger.debug(f"dropping response for unknown request id {parsed}")
                continue
            future = pending[0]
            if future.done():
                continue
            if parsed.get("ok"):
                future.set_result(parsed.get("payload") or {})
            else:
                error = parsed.get("error") or {}
                future.set_exception(
                    self._create_helper_error(
                        error.get("message", "RDP helper request failed"),
                        error.get("code"),
                        diagnostics,
                    )
                )

    async def _read_stderr(self, child, diagnostics):
        stderr = child.stderr
        while True:
            chunk = await stderr.read(4096)
            if not chunk:
                return
            diagnostics.capture_stderr(chunk.decode("utf-8", errors="replace"))

    async def _watch_exit(self, child, diagnostics):
        code = await child.wait()
        diagnostics.exit_code = code
        diagnostics.exit_signal = None
        logger.debug(
            f"rdp helper exited path={diagnostics.path} pid={diagnostics.pid} "
            f"code={code}"
        )
        helper_error = self._create_helper_error(
            f"RDP helper exited unexpectedly (code={code}, signal=null)",
            None,
            diagnostics,
        )
        self._reject_pending_for_child(child, helper_error)
        if self._child is child:
            self._connected = False
            self._fatal_helper_error = helper_error
            self._dispose_readers(except_task=asyncio.current_task())
            self._child = None

    async def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if (
            payload.get("type") != "connect"
            and self._fatal_helper_error is not None
            and (self._child is None or self._child.returncode is not None)
        ):
            raise self._fatal_helper_error

        child = await self._ensure_helper_started()
        if child.returncode is not None:
            raise self._create_helper_error("RDP helper is not running")

        self._next_request_id += 1
        request_id = f"req-{self._next_request_id}"
        diagnostics = self._diagnostics.get(id(child))
        request = {"id": request_id, "payload": payload}

        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (future, child)
        try:
            child.stdin.write(
                (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await child.stdin.drain()
        except (OSError, ConnectionError, RuntimeError) as error:
            self._pending.pop(request_id, None)
            asyncio.ensure_future(
                self._reject_write_failure(
                    child, request_id, future, payload, error, diagnostics
                )
            )
        return await future

    async def _reject_write_failure(
        self,
        child,
        request_id: str,
        future: asyncio.Future,
        payload: Dict[str, Any],
        error: BaseException,
        diagnostics: Optional[_HelperDiagnostics],
    ) -> None:
        await asyncio.sleep(HELPER_WRITE_ERROR_DIAGNOSTIC_DELAY_S)
        if future.done():
            return
        if child.returncode is not None:
            future.set_exception(
                self._create_helper_error(
                    f"Failed to send {payload.get('type')} request to RDP "
                    f"helper: {error}",
                    getattr(error, "code", None),
                    diagnostics,
                )
            )
            return
        stream_error = self._create_helper_error(
            f"RDP helper stdin stream error: {error}",
            getattr(error, "code", None),
            diagnostics,
        )
        self._reject_pending_for_child(child, stream_error)
        if self._child is child:
            self._connected = False
            self._fatal_helper_error = stream_error
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            self._child = None
        if not future.done():
            future.set_exception(stream_error)

    def _expect_ok(self, response: Dict[str, Any], action_name: str) -> None:
        if response.get("type") != "ok":
            raise RuntimeError(
                f"Expected ok response for {action_name}, got "
                f"{response.get('type')}"
            )

    def _reject_pending_for_child(self, child, error: BaseException) -> None:
        for request_id, (future, pending_child) in list(self._pending.items()):
            if pending_child is not child:
                continue
            self._pending.pop(request_id, None)
            if not future.done():
                future.set_exception(error)

    def _reject_pending(self, error: BaseException) -> None:
        for future, _child in list(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    def _create_helper_error(
        self,
        message: str,
        code: Optional[str] = None,
        diagnostics: Optional[_HelperDiagnostics] = None,
    ) -> RuntimeError:
        parts = []
        if diagnostics is not None:
            if diagnostics.path:
                parts.append(f"path={diagnostics.path}")
            if diagnostics.pid is not None:
                parts.append(f"pid={diagnostics.pid}")
            if diagnostics.exit_code is not None:
                parts.append(
                    f"exitCode={diagnostics.exit_code}, signal=null"
                )
        suffix = f"\nHelper diagnostics: {', '.join(parts)}" if parts else ""
        stderr_summary = diagnostics.stderr_buffer.strip() if diagnostics else ""
        stderr_suffix = (
            f"\nHelper stderr:\n{stderr_summary}" if stderr_summary else ""
        )
        error = RuntimeError(f"{message}{suffix}{stderr_suffix}")
        if code:
            error.code = code  # type: ignore[attr-defined]
        return error

    def _dispose_readers(self, except_task: Optional[asyncio.Task] = None) -> None:
        current = asyncio.current_task()
        for task in self._reader_tasks:
            if task is except_task or task is current or task.done():
                continue
            task.cancel()
        self._reader_tasks = []

    async def _shutdown_helper(
        self, root_error: Optional[BaseException] = None
    ) -> None:
        child = self._child
        self._child = None
        self._dispose_readers()

        if child is None:
            return

        self._reject_pending(
            root_error or self._create_helper_error("RDP helper shut down")
        )

        if child.returncode is not None:
            return

        try:
            child.stdin.close()
        except (OSError, AttributeError):
            pass

        try:
            await asyncio.wait_for(
                child.wait(), timeout=HELPER_SHUTDOWN_TIMEOUT_S
            )
            return
        except asyncio.TimeoutError:
            pass

        try:
            child.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(
                child.wait(), timeout=HELPER_SHUTDOWN_TIMEOUT_S
            )
            return
        except asyncio.TimeoutError:
            pass

        try:
            child.kill()
        except ProcessLookupError:
            return
        await child.wait()


def _is_shutdown_error(error: BaseException) -> bool:
    message = str(error)
    return any(
        marker in message
        for marker in (
            "RDP helper exited unexpectedly",
            "RDP helper is not running",
            "RDP helper shut down",
        )
    )


def create_default_rdp_backend_client() -> RDPBackendClient:
    """Default backend factory (upstream createDefaultRDPBackendClient)."""
    return HelperProcessRDPBackendClient()


__all__ = [
    "HelperProcessRDPBackendClient",
    "UnsupportedRDPBackendClient",
    "create_default_rdp_backend_client",
]
