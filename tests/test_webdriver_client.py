"""Synced from upstream ``packages/webdriver/tests/unit-test/base-url.test.ts``
and ``packages/webdriver/tests/unit-test/buildSessionEndpoint.test.ts``.

The Python ``WebDriverClient`` keeps the upstream session lifecycle,
screenshot/window-size endpoints and device-info lookup exercised by the
base-URL and session-endpoint suites.
"""

import re
from typing import Any, Dict, List

import pytest


class FakeWDAHttp:
    """Records requests and returns canned parsed responses (make_request
    returns the parsed JSON body, so the stub does the same)."""

    def __init__(self, responses: Dict[str, Any]):
        self.responses = responses
        self.requests: List[tuple] = []

    async def __call__(self, method, url, json=None):
        self.requests.append((method, url, json))
        tail = url.split("://", 1)[-1].split("/", 1)[-1]
        # normalize /session/<id>/... to /session/... so patterns don't need ids
        key = f"{method} {tail}"
        normalized = re.sub(
            r"^(GET|POST|DELETE) session/[^/]+", r"\1 session", key
        )
        for pattern, payload in self.responses.items():
            if normalized.startswith(pattern) or key.startswith(pattern):
                return payload
        raise RuntimeError(
            f"WebDriver request failed (404) {method} {tail}: not found"
        )


@pytest.mark.asyncio
async def test_preserves_the_gateway_prefix_for_session_and_command_requests():
    from midscene.webdriver import WebDriverClient

    http = FakeWDAHttp(
        {
            "POST session": {
                "sessionId": "s1",
                "capabilities": {"platformName": "iOS"},
            },
            "DELETE session": {"value": None},
        }
    )
    client = WebDriverClient(base_url="http://localhost:8100")
    client.make_request = http

    session = await client.create_session({"platformName": "iOS"})
    assert session["sessionId"] == "s1"
    assert client.session_id == "s1"
    assert client.owns_session is True

    await client.delete_session()
    assert client.session_id is None


@pytest.mark.asyncio
async def test_take_screenshot_and_window_size():
    from midscene.webdriver import WebDriverClient

    http = FakeWDAHttp(
        {
            "GET session/screenshot": {"value": "base64png"},
            "GET session/window/rect": {"value": {"width": 390, "height": 844}},
        }
    )
    client = WebDriverClient(
        base_url="http://localhost:8100", session_id="ext-1"
    )
    client.make_request = http
    # external session: owns_session False
    assert client.owns_session is False

    assert await client.take_screenshot() == "base64png"
    size = await client.get_window_size()
    assert size == (390, 844)


@pytest.mark.asyncio
async def test_window_size_falls_back_to_size_endpoint():
    from midscene.webdriver import WebDriverClient

    http = FakeWDAHttp(
        {"GET session/window/size": {"value": {"width": 100, "height": 200}}}
    )
    client = WebDriverClient(base_url="http://x", session_id="s")

    async def fail_rect(method, path, body=None):
        if "rect" in path:
            raise RuntimeError("no rect endpoint")
        return await http(method, path, body)

    client.make_request = fail_rect
    assert await client.get_window_size() == (100, 200)


@pytest.mark.asyncio
async def test_device_info_from_status():
    from midscene.webdriver import WebDriverClient

    http = FakeWDAHttp(
        {
            "GET status": {
                "device": {"udid": "UDID-1", "name": "iPhone", "model": "15 Pro"}
            }
        }
    )
    client = WebDriverClient(base_url="http://x")
    client.make_request = http
    info = await client.get_device_info()
    assert info["udid"] == "UDID-1"
    assert info["model"] == "15 Pro"
