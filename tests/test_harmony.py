"""
Tests for the HarmonyOS device layer (upstream packages/harmony).
All hdc invocations go through a fake HdcClient; no device required.
"""

import asyncio
import base64
import io
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from midscene.harmony.hdc import HdcClient, resolve_hdc_path


class FakeHdc:
    """Records hdc-level operations and returns canned outputs."""

    def __init__(self, screen: Dict[str, int] = None):
        self.calls: List[tuple] = []
        self.screen = screen or {"width": 1260, "height": 2720}
        self.snapshot_output = "width 1260, height 2720"

    async def _record(self, op: str, *args):
        self.calls.append((op, *args))

    async def click(self, x, y):
        await self._record("click", x, y)

    async def double_click(self, x, y):
        await self._record("doubleClick", x, y)

    async def long_click(self, x, y):
        await self._record("longClick", x, y)

    async def swipe(self, fx, fy, tx, ty, speed=None):
        await self._record("swipe", fx, fy, tx, ty, speed)

    async def fling(self, fx, fy, tx, ty, speed=None):
        await self._record("fling", fx, fy, tx, ty, speed)

    async def drag(self, fx, fy, tx, ty, speed=None):
        await self._record("drag", fx, fy, tx, ty, speed)

    async def input_text(self, x, y, text):
        await self._record("inputText", x, y, text)

    async def key_event(self, *keys):
        await self._record("keyEvent", *keys)

    async def screenshot(self, remote_path):
        await self._record("screenshot", remote_path)
        return self.snapshot_output

    async def file_recv(self, remote, local):
        await self._record("fileRecv", remote, local)
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (1260, 2720), (0, 0, 0)).save(buffer, format="JPEG")
        with open(local, "wb") as f:
            f.write(buffer.getvalue())

    async def get_screen_info(self):
        return dict(self.screen)

    async def launch(self, uri):
        await self._record("launch", uri)

    async def force_stop(self, bundle):
        await self._record("force_stop", bundle)

    async def shell(self, command):
        await self._record("shell", command)
        return ""


def _device():
    from midscene.harmony.device import HarmonyDevice

    device = HarmonyDevice()
    device.hdc = FakeHdc()
    device._connected = True
    return device


class TestHdcHelpers:
    def test_resolve_hdc_path_env(self, monkeypatch):
        monkeypatch.setenv("HDC_HOME", "/opt/harmony/sdk")
        assert resolve_hdc_path() == "/opt/harmony/sdk/hdc"

    def test_resolve_hdc_path_explicit(self):
        assert resolve_hdc_path("/usr/bin/hdc") == "/usr/bin/hdc"

    def test_round_coordinate_rejects_nan(self):
        with pytest.raises(ValueError):
            from midscene.harmony.hdc import round_ui_coordinate

            round_ui_coordinate(float("nan"))

    def test_round_speed(self):
        from midscene.harmony.hdc import round_ui_input_speed

        assert round_ui_input_speed(123.4) == 123

    @pytest.mark.asyncio
    async def test_exec_serializes_and_builds_args(self):
        client = HdcClient(device_id="em-1", hdc_path="/fake/hdc")
        calls: List[List[str]] = []
        release = asyncio.Event()
        release.set()

        async def fake_create_subprocess_exec(*args, **kwargs):
            calls.append(list(args))
            proc = MagicMock()
            proc.returncode = 0

            async def communicate():
                return (b"out", b"")

            proc.communicate = communicate
            return proc

        with patch(
            "asyncio.create_subprocess_exec", new=fake_create_subprocess_exec
        ):
            await asyncio.gather(client.shell("a"), client.shell("b"))
        assert len(calls) == 2
        # args[0] is the hdc binary; device selector follows it
        assert all(args[1:3] == ["-t", "em-1"] for args in calls)

    @pytest.mark.asyncio
    async def test_key_event_validation(self):
        client = HdcClient(hdc_path="/fake/hdc")
        client.shell = AsyncMock(return_value="")

        await client.key_event("2054")
        client.shell.assert_awaited_with("uitest uiInput keyEvent 2054")

        with pytest.raises(RuntimeError):
            await client.key_event("Back", "2054")  # string + numeric mix
        with pytest.raises(RuntimeError):
            await client.key_event("NotAKey")

    @pytest.mark.asyncio
    async def test_input_text_escapes_quotes(self):
        client = HdcClient(hdc_path="/fake/hdc")
        client.shell = AsyncMock(return_value="")

        await client.input_text(10, 20, "it's")
        sent = client.shell.await_args_list[0].args[0]
        assert "it'\\''s" in sent

    @pytest.mark.asyncio
    async def test_screen_info_foldable(self):
        client = HdcClient(hdc_path="/fake/hdc")
        client.shell = AsyncMock(return_value=(
            "screen[0]: id=0, isConnected=1, isPowerOn:1\n"
            "foldScreenId:0, isConnected=1, isPowerOn:1\n"
            "  render size = 2000x2800"
        ))
        info = await client.get_screen_info()
        assert info == {"width": 2000, "height": 2800}


class TestKeycode:
    def test_named_codes(self):
        from midscene.harmony.keycode import resolve_harmony_key_codes as resolve

        assert resolve("Enter") == ["2054"]
        assert resolve("Escape") == ["2070"]
        assert resolve("Back") == ["Back"]

    def test_letters_and_digits(self):
        from midscene.harmony.keycode import resolve_harmony_key_codes as resolve

        assert resolve("A") == ["2017"]
        assert resolve("z") == ["2042"]
        assert resolve("1") == ["2001"]

    def test_aliases(self):
        from midscene.harmony.keycode import resolve_harmony_key_codes as resolve

        assert resolve("ctrl") == ["2072"]
        assert resolve("esc") == ["2070"]

    def test_combinations_rejected(self):
        from midscene.harmony.keycode import resolve_harmony_key_codes as resolve

        with pytest.raises(RuntimeError) as exc:
            resolve("Control+A")
        assert "combinations" in str(exc.value)

    def test_unknown_key(self):
        from midscene.harmony.keycode import resolve_harmony_key_codes as resolve

        with pytest.raises(RuntimeError):
            resolve("F13")


class TestSwipeSpeed:
    def test_clamped_to_range(self):
        from midscene.harmony.swipe import resolve_swipe_speed

        # tiny distance in tiny duration -> clamped to min 200
        assert resolve_swipe_speed({"x": 0, "y": 0}, {"x": 1, "y": 0}, 100) == 200
        # huge distance -> clamped to max 40000
        assert resolve_swipe_speed(
            {"x": 0, "y": 0}, {"x": 10000, "y": 0}, 10
        ) == 40000

    def test_exact_speed(self):
        from midscene.harmony.swipe import resolve_swipe_speed

        assert resolve_swipe_speed({"x": 0, "y": 0}, {"x": 300, "y": 400}, 1000) == 500

    def test_invalid_duration(self):
        from midscene.harmony.swipe import resolve_swipe_speed

        with pytest.raises(RuntimeError):
            resolve_swipe_speed({"x": 0, "y": 0}, {"x": 1, "y": 0}, 0)


class TestHarmonyDevice:
    @pytest.mark.asyncio
    async def test_get_context_from_snapshot(self):
        device = _device()
        context = await device.get_context()
        assert context.size.width == 1260
        assert context.size.height == 2720
        # screen size updated from the snapshot output
        assert device.cached_screen_size == {"width": 1260, "height": 2720}
        base64.b64decode(context.screenshot_base64)

    @pytest.mark.asyncio
    async def test_tap_and_text(self):
        device = _device()
        await device.tap(100, 200)
        assert ("click", 100, 200) in device.hdc.calls
        await device.input_text_at(100, 200, "你好鸿蒙")
        assert ("inputText", 100, 200, "你好鸿蒙") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_input_action_uses_coordinate_input(self):
        from midscene.core.actions import (
            build_action_space_for,
            find_action_in_action_space_or_throw,
        )

        device = _device()

        async def fake_locate(param):
            return {"center": (100, 200), "rect": None, "description": "x"}

        definition = find_action_in_action_space_or_throw(
            "Input", build_action_space_for("harmony")
        )
        await definition.execute(
            {"value": "hello", "locate": {"prompt": "the field"}},
            device,
            fake_locate,
        )
        assert ("inputText", 100, 200, "hello") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_keyboard_press_resolves_codes(self):
        device = _device()
        await device.keyboard_press("Enter")
        assert ("keyEvent", "2054") in device.hdc.calls

        with pytest.raises(RuntimeError):
            await device.keyboard_press("Control+A")

    @pytest.mark.asyncio
    async def test_scroll_uses_fling_with_edge_margin(self):
        device = _device()
        await device.scroll("down", 800)
        flings = [c for c in device.hdc.calls if c[0] == "fling"]
        assert flings, "expected a fling call"
        _, fx, fy, tx, ty, _speed = flings[0]
        # endpoints stay within the screen bounds
        assert 0 <= tx <= 1260
        assert 0 <= ty <= 2720

    @pytest.mark.asyncio
    async def test_swipe_finger_convention(self):
        device = _device()
        await device.swipe("up", distance=400)
        swipes = [c for c in device.hdc.calls if c[0] == "swipe"]
        assert swipes
        _, fx, fy, tx, ty, _speed = swipes[0]
        # finger moves up: end y < start y
        assert ty < fy

    @pytest.mark.asyncio
    async def test_system_buttons(self):
        device = _device()
        await device.back()
        await device.home()
        assert ("keyEvent", "Back") in device.hdc.calls
        assert ("keyEvent", "Home") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_launch_and_terminate(self):
        device = _device()
        await device.launch_app("com.example.app")
        assert ("launch", "com.example.app") in device.hdc.calls
        await device.stop_app("com.example.app")
        assert ("force_stop", "com.example.app") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_run_hdc_shell(self):
        device = _device()
        result = await device.run_hdc_shell("hidumper -s RenderService -a screen")
        assert ("shell", "hidumper -s RenderService -a screen") in device.hdc.calls
        assert result == ""

    def test_harmony_action_space(self):
        from midscene.core.actions import build_action_space_for

        names = [a.name for a in build_action_space_for("harmony")]
        assert {
            "RunHdcShell", "Launch", "Terminate",
            "HarmonyBackButton", "HarmonyHomeButton",
            "HarmonyRecentAppsButton",
        } <= set(names)
        assert "Pinch" not in names and "RightClick" not in names

    def test_harmony_agent(self):
        from midscene.harmony import HarmonyAgent

        agent = HarmonyAgent(_device())
        assert agent.interface_type.value == "harmony"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
