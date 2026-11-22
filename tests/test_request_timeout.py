"""Synced from upstream packages/webdriver/tests/unit-test/request-timeout.test.ts."""

import http.server
import threading
import time

import pytest

from midscene.webdriver.utils.request import (
    WebDriverRequestError,
    make_webdriver_request,
)


class _SlowBodyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    content_type = "application/json"
    body_parts = (b"", b"")

    def do_GET(self):
        first, second = self.body_parts
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(first) + len(second)))
        self.end_headers()
        self.wfile.write(first)
        self.wfile.flush()
        # Complete eventually so a missing deadline fails instead of hanging.
        time.sleep(0.25)
        try:
            self.wfile.write(second)
            self.wfile.flush()
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def start_slow_body_server():
    servers = []

    def start(content_type):
        handler = type(
            "Handler",
            (_SlowBodyHandler,),
            {
                "content_type": content_type,
                "body_parts": (
                    (b'{"value":', b"true}")
                    if content_type == "application/json"
                    else (b"pending", b"done")
                ),
            },
        )
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return server.server_address[1]

    yield start

    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
async def test_keeps_the_deadline_active_while_reading_a_body(
    start_slow_body_server, content_type
):
    """keeps the deadline active while reading a %s body"""
    port = start_slow_body_server(content_type)

    with pytest.raises(WebDriverRequestError) as excinfo:
        await make_webdriver_request(
            f"http://127.0.0.1:{port}",
            "GET",
            "/element/active",
            None,
            80,
        )

    assert "timeout after 80ms" in str(excinfo.value)
