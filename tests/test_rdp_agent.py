"""Synced from upstream ``packages/computer/tests/unit-test/rdp/agent.test.ts``
and ``packages/computer/src/rdp/{backend-client,helper-binary}.ts``.

The Python RDP device mirrors the upstream device surface: connect/context,
pointer and keyboard primitives, the unimplemented default transport and the
per-platform helper binary lookup.
"""

from typing import List

import pytest


class FakeRDPBackend:
    def __init__(self):
        self.calls: List[tuple] = []

    async def connect(self, config):
        self.calls.append(("connect", config))
        return {
            "sessionId": "rdp-1",
            "size": {"width": 1280, "height": 720},
            "server": config["host"],
        }

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def screenshot_base64(self):
        self.calls.append(("screenshot",))
        return "base64png"

    async def size(self):
        self.calls.append(("size",))
        return {"width": 1280, "height": 720}

    async def mouse_move(self, x, y):
        self.calls.append(("mouse_move", x, y))

    async def mouse_button(self, button, action):
        self.calls.append(("mouse_button", button, action))

    async def wheel(self, direction, amount, x=None, y=None):
        self.calls.append(("wheel", direction, amount))

    async def key_press(self, key_name):
        self.calls.append(("key_press", key_name))

    async def type_text(self, text):
        self.calls.append(("type_text", text))


@pytest.mark.asyncio
async def test_connects_and_exposes_the_rdp_device_through_agent():
    from midscene.computer.rdp import RDPDevice

    backend = FakeRDPBackend()
    device = RDPDevice({"host": "win-box"}, backend=backend)
    assert device.interface_type.value == "computer"
    await device.connect()
    context = await device.get_context()
    assert context.size.width == 1280
    assert any(c[0] == "screenshot" for c in backend.calls)


@pytest.mark.asyncio
async def test_translates_tap_into_backend_pointer_calls():
    from midscene.computer.rdp import RDPDevice

    backend = FakeRDPBackend()
    device = RDPDevice({"host": "win-box"}, backend=backend)
    await device.tap(10, 20)
    await device.right_click(10, 20)
    await device.double_click(10, 20)
    await device.input_text("hello")
    await device.keyboard_press("Enter")
    await device.scroll("down", 300)
    assert ("mouse_move", 10, 20) in backend.calls
    assert ("mouse_button", "right", "click") in backend.calls
    assert ("mouse_button", "left", "doubleClick") in backend.calls
    assert ("type_text", "hello") in backend.calls
    assert ("key_press", "Enter") in backend.calls
    assert ("wheel", "down", 300) in backend.calls


@pytest.mark.asyncio
async def test_default_backend_raises_not_implemented():
    """Faithful upstream state: the transport is unimplemented until a
    custom backend is injected."""
    from midscene.computer.rdp import RDPDevice

    device = RDPDevice({"host": "win-box"})
    with pytest.raises(RuntimeError) as exc:
        await device.connect()
    assert "not implemented yet" in str(exc.value)


def test_helper_binary_missing_reports_platform():
    from midscene.computer.rdp import get_rdp_helper_binary_path

    with pytest.raises(RuntimeError) as exc:
        get_rdp_helper_binary_path(package_root="/nonexistent")
    assert "rdp-helper" in str(exc.value)
