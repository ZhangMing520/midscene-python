"""Synced from upstream
``packages/computer/tests/unit-test/rdp/backend-client.test.ts``.

The Node streams are replaced by an asyncio fake child process that exposes
the same stdin/stdout/stderr/wait/kill surface used by
``HelperProcessRDPBackendClient``.
"""

import asyncio
import json

import pytest

from midscene.computer.rdp.backend_client import (
    HelperProcessRDPBackendClient,
)


class FakePipeError(OSError):
    def __init__(self):
        super().__init__("write EPIPE")
        self.code = "EPIPE"


class FakeReader:
    """Minimal asyncio StreamReader replacement for helper stdout/stderr."""

    def __init__(self):
        self._queue = asyncio.Queue()
        self._buffer = b""
        self._eof = False
        self._eof_queued = False

    def feed_data(self, data):
        self._queue.put_nowait(data)

    def feed_eof(self):
        if self._eof_queued:
            return
        self._eof_queued = True
        self._queue.put_nowait(None)

    async def _fill(self):
        chunk = await self._queue.get()
        if chunk is None:
            self._eof = True
        else:
            self._buffer += chunk

    async def readline(self):
        while b"\n" not in self._buffer and not self._eof:
            await self._fill()
        if b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            return line + b"\n"
        if self._buffer:
            line, self._buffer = self._buffer, b""
            return line
        return b""

    async def read(self, size=-1):
        while not self._buffer and not self._eof:
            await self._fill()
        if not self._buffer:
            return b""
        if size is None or size < 0:
            data, self._buffer = self._buffer, b""
            return data
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data


class FakeStdin:
    def __init__(self, child):
        self._child = child

    def write(self, data):
        if self._child.next_write_error is not None:
            error = self._child.next_write_error
            self._child.next_write_error = None
            raise error
        if self._child.on_write is not None:
            self._child.on_write(data)

    async def drain(self):
        return None

    def close(self):
        if self._child.returncode is None:
            self._child.emit_exit(0)


class FakeChildProcess:
    def __init__(self):
        self.stdout = FakeReader()
        self.stderr = FakeReader()
        self.stdin = FakeStdin(self)
        self.pid = 4242
        self.returncode = None
        self.killed = False
        self.next_write_error = None
        self.on_write = None
        self._exit = asyncio.Event()

    def fail_next_stdin_write(self, error):
        self.next_write_error = error

    def write_response(self, response):
        self.stdout.feed_data((json.dumps(response) + "\n").encode("utf-8"))

    def write_stdout(self, text):
        self.stdout.feed_data(text.encode("utf-8"))

    def write_stderr(self, text):
        self.stderr.feed_data(text.encode("utf-8"))

    def emit_exit(self, code):
        self.returncode = code
        self._exit.set()

    def kill(self, signal=None):
        self.killed = True
        if self.returncode is None:
            self.emit_exit(signal if isinstance(signal, int) else 1)
        return True

    def terminate(self):
        return self.kill()

    async def wait(self):
        await self._exit.wait()
        return self.returncode


def create_client_with_child():
    child = FakeChildProcess()
    client = HelperProcessRDPBackendClient(
        {"spawnFn": lambda _path: child, "helperPath": "/fake/rdp-helper"}
    )
    return child, client


def on_next_request(child, handler):
    handled = {"value": False}

    def on_write(data):
        if handled["value"]:
            return
        handled["value"] = True
        handler(json.loads(data.decode("utf-8")))

    child.on_write = on_write


def _connected(server="10.75.166.249:3389", session="session-1"):
    return {
        "type": "connected",
        "info": {
            "sessionId": session,
            "server": server,
            "size": {"width": 1280, "height": 720},
        },
    }


def test_parses_successful_helper_responses():
    """parses successful helper responses"""
    child, client = create_client_with_child()

    def handler(request):
        assert request["payload"]["type"] == "connect"
        child.write_response(
            {"id": request["id"], "ok": True, "payload": _connected()}
        )

    on_next_request(child, handler)

    result = asyncio.run(
        client.connect({"host": "10.75.166.249", "username": "Admin"})
    )

    assert result == {
        "sessionId": "session-1",
        "server": "10.75.166.249:3389",
        "size": {"width": 1280, "height": 720},
    }


def test_normalizes_bracketed_ipv6_hosts_before_sending_helper_connect_requests():
    """normalizes bracketed IPv6 hosts before sending helper connect requests"""
    child, client = create_client_with_child()

    def handler(request):
        payload = request["payload"]
        assert payload["type"] == "connect"
        assert payload["config"]["host"] == "2001:db8::42"
        assert payload["config"]["port"] == 3390
        child.write_response(
            {
                "id": request["id"],
                "ok": True,
                "payload": _connected(
                    server="[2001:db8::42]:3390", session="session-ipv6"
                ),
            }
        )

    on_next_request(child, handler)

    result = asyncio.run(
        client.connect(
            {"host": "[2001:db8::42]", "port": 3390, "username": "Admin"}
        )
    )

    assert result["sessionId"] == "session-ipv6"
    assert result["server"] == "[2001:db8::42]:3390"


def test_forwards_local_address_in_helper_connect_requests():
    """forwards localAddress in helper connect requests"""
    child, client = create_client_with_child()

    def handler(request):
        payload = request["payload"]
        assert payload["type"] == "connect"
        assert payload["config"]["host"] == "10.75.166.249"
        assert payload["config"]["localAddress"] == "10.75.166.10"
        child.write_response(
            {
                "id": request["id"],
                "ok": True,
                "payload": _connected(session="session-local-address"),
            }
        )

    on_next_request(child, handler)

    result = asyncio.run(
        client.connect(
            {
                "host": "10.75.166.249",
                "localAddress": "10.75.166.10",
                "username": "Admin",
            }
        )
    )

    assert result["sessionId"] == "session-local-address"


def test_rejects_structured_helper_errors():
    """rejects structured helper errors"""
    child, client = create_client_with_child()

    def handler(request):
        child.write_response(
            {
                "id": request["id"],
                "ok": False,
                "error": {
                    "code": "connect_failed",
                    "message": "Authentication failed",
                },
            }
        )

    on_next_request(child, handler)

    with pytest.raises(RuntimeError, match="Authentication failed") as info:
        asyncio.run(
            client.connect({"host": "10.75.166.249", "username": "Admin"})
        )
    assert info.value.code == "connect_failed"


def test_rejects_all_pending_requests_if_the_helper_exits_unexpectedly():
    """rejects all pending requests if the helper exits unexpectedly"""
    child, client = create_client_with_child()

    async def scenario():
        connect_task = asyncio.ensure_future(
            client.connect({"host": "10.75.166.249", "username": "Admin"})
        )
        screenshot_task = asyncio.ensure_future(client.screenshot_base64())
        await asyncio.sleep(0.02)
        child.emit_exit(1)
        with pytest.raises(RuntimeError, match="RDP helper exited unexpectedly"):
            await connect_task
        with pytest.raises(RuntimeError, match="RDP helper exited unexpectedly"):
            await screenshot_task

    asyncio.run(scenario())


def test_rejects_pending_requests_if_the_helper_stdin_pipe_breaks():
    """rejects pending requests if the helper stdin pipe breaks"""
    child, client = create_client_with_child()
    child.fail_next_stdin_write(FakePipeError())

    with pytest.raises(
        RuntimeError, match="RDP helper stdin stream error: write EPIPE"
    ):
        asyncio.run(
            client.connect({"host": "10.75.166.249", "username": "Admin"})
        )
    assert child.killed is True


def test_includes_helper_diagnostics_when_the_first_connect_write_fails_after_early_helper_exit():
    """includes helper diagnostics when the first connect write fails after early helper exit"""
    child, client = create_client_with_child()
    child.fail_next_stdin_write(FakePipeError())

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.call_later(
            0.01,
            lambda: (
                child.write_stderr(
                    "error while loading shared libraries: libfreerdp2.so: "
                    "cannot open shared object file"
                ),
                child.emit_exit(127),
            ),
        )
        with pytest.raises(RuntimeError) as info:
            await client.connect(
                {"host": "10.75.166.249", "username": "Admin"}
            )
        return str(info.value)

    message = asyncio.run(scenario())

    assert "Failed to send connect request to RDP helper: write EPIPE" in message
    assert "path=/fake/rdp-helper" in message
    assert "pid=4242" in message
    assert "exitCode=127, signal=null" in message
    assert "libfreerdp2.so" in message


def test_rejects_old_helper_pending_requests_after_a_reconnect_starts_a_new_helper():
    """rejects old helper pending requests after a reconnect starts a new helper"""
    first_child = FakeChildProcess()
    second_child = FakeChildProcess()
    children = [first_child, second_child]
    spawn_count = {"value": 0}

    def spawn(_path):
        child = children[spawn_count["value"]]
        spawn_count["value"] += 1
        return child

    client = HelperProcessRDPBackendClient(
        {"spawnFn": spawn, "helperPath": "/fake/rdp-helper"}
    )

    def first_handler(request):
        first_child.write_response(
            {"id": request["id"], "ok": True, "payload": _connected()}
        )

    on_next_request(first_child, first_handler)

    async def scenario():
        await client.connect({"host": "10.75.166.249", "username": "Admin"})
        screenshot_task = asyncio.ensure_future(client.screenshot_base64())
        await asyncio.sleep(0.02)
        first_child.write_stderr("first helper crashed before screenshot response")
        first_child.emit_exit(1)

        def second_handler(request):
            second_child.write_response(
                {
                    "id": request["id"],
                    "ok": True,
                    "payload": _connected(session="session-2"),
                }
            )

        on_next_request(second_child, second_handler)
        result = await client.connect(
            {"host": "10.75.166.249", "username": "Admin"}
        )
        with pytest.raises(
            RuntimeError, match="RDP helper exited unexpectedly"
        ) as info:
            await screenshot_task
        return result, str(info.value)

    result, screenshot_error = asyncio.run(scenario())

    assert result["sessionId"] == "session-2"
    assert "first helper crashed before screenshot response" in screenshot_error
    assert spawn_count["value"] == 2


def test_throws_on_malformed_helper_output():
    """throws on malformed helper output"""
    child, client = create_client_with_child()

    on_next_request(child, lambda _request: child.write_stdout("this is not json\n"))

    with pytest.raises(RuntimeError, match="RDP helper emitted malformed JSON"):
        asyncio.run(client.connect({"host": "10.75.166.249"}))


def test_surfaces_the_original_helper_exit_instead_of_silently_restarting_an_empty_helper():
    """surfaces the original helper exit instead of silently restarting an empty helper"""
    first_child = FakeChildProcess()
    second_child = FakeChildProcess()
    children = [first_child, second_child]
    spawn_count = {"value": 0}

    def spawn(_path):
        child = children[spawn_count["value"]]
        spawn_count["value"] += 1
        return child

    client = HelperProcessRDPBackendClient(
        {"spawnFn": spawn, "helperPath": "/fake/rdp-helper"}
    )
    on_next_request(
        first_child,
        lambda request: first_child.write_response(
            {"id": request["id"], "ok": True, "payload": _connected()}
        ),
    )

    async def scenario():
        await client.connect({"host": "10.75.166.249", "username": "Admin"})
        first_child.emit_exit(1)
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="RDP helper exited unexpectedly"):
            await client.size()

    asyncio.run(scenario())

    assert spawn_count["value"] == 1
