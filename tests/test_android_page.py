"""Synced from upstream ``packages/android/tests/unit-test/page.test.ts``.

Covers the input-routing, action-space registration and scroll geometry cases
ported by the Python Android device.
"""

from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestAndroidInputRouting:
    def test_should_use_yadb_for_text(self):
        from midscene.android.device import should_use_yadb_for_text

        assert should_use_yadb_for_text("中文输入") is True
        assert should_use_yadb_for_text("café") is True
        # upstream regex /%[a-zA-Z]/: only %-immediately-followed-by-letter
        assert should_use_yadb_for_text("%s") is True
        assert should_use_yadb_for_text("50% off") is False
        assert should_use_yadb_for_text("back\\slash") is True
        assert should_use_yadb_for_text("a\"b'c") is True
        assert should_use_yadb_for_text("plain text 123") is False

    @pytest.mark.asyncio
    async def test_space_hello_world(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        monkeypatch.setenv("MIDSCENE_ANDROID_IME_STRATEGY", "legacy")
        device = AndroidDevice("emulator-5554")
        device._connected = True
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        await device.input_text("hello world")
        assert commands == [
            ["-s", "emulator-5554", "shell", "input", "text", "'hello world'"]
        ]

    @pytest.mark.asyncio
    async def test_yadb_for_non_ascii_non_ascii_uses_yadb(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("emulator-5554")
        device._connected = True
        calls: List[str] = []

        async def fake_exec(content):
            calls.append(content)

        device._exec_yadb_raw = fake_exec
        await device.input_text("你好 world")
        assert calls == ["你好 world"]

    @pytest.mark.asyncio
    async def test_middle_newline_line1_line2(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        monkeypatch.setenv("MIDSCENE_ANDROID_IME_STRATEGY", "legacy")
        device = AndroidDevice("emulator-5554")
        device._connected = True
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        await device.input_text("a\nb")
        assert commands[0][-1] == "'a'"
        assert "KEYCODE_ENTER" in commands[1]
        assert commands[2][-1] == "'b'"


class TestAndroidActionSpace:
    def test_includes_run_adb_shell_by_default(self):
        from midscene.core.device import build_android_action_space

        names = [a.name for a in build_android_action_space()]
        assert {"RunAdbShell", "Launch", "Terminate"} <= set(names)

    @pytest.mark.asyncio
    async def test_should_pass_timeout_through_the_run_adb_shell_action(self):
        from midscene.core.device import (
            build_android_action_space,
            find_action_in_action_space_or_throw,
        )

        executed: List[str] = []

        class Device:
            async def run_adb_shell(self, command, timeout=None):
                executed.append((command, timeout))

        definition = find_action_in_action_space_or_throw(
            "RunAdbShell", build_android_action_space()
        )
        await definition.execute({"command": "ls", "timeout": 1000}, Device(), None)
        assert executed == [("ls", 1000.0)]

    @pytest.mark.asyncio
    async def test_should_call_page_launch_and_terminate_with_the_given_uri(self):
        """Upstream agent.test.ts: ``should call page.launch with the given uri``
        and ``should call page.terminate with the given uri``."""
        from midscene.core.device import (
            build_android_action_space,
            find_action_in_action_space_or_throw,
        )

        calls: List[tuple] = []

        class Device:
            async def launch_app(self, uri):
                calls.append(("launch", uri))

            async def stop_app(self, uri):
                calls.append(("terminate", uri))

        space = build_android_action_space()
        await find_action_in_action_space_or_throw("Launch", space).execute(
            {"uri": "com.a.b"}, Device(), None
        )
        await find_action_in_action_space_or_throw("Terminate", space).execute(
            {"uri": "com.a.b"}, Device(), None
        )
        assert calls == [("launch", "com.a.b"), ("terminate", "com.a.b")]

    @pytest.mark.asyncio
    async def test_launch_param_schema_is_a_zod_object_with_a_uri_zod_string_field(self):
        from midscene.core.device import (
            build_android_action_space,
            find_action_in_action_space_or_throw,
        )

        space = build_android_action_space()
        with pytest.raises(ValueError):
            await find_action_in_action_space_or_throw("Launch", space).execute(
                {}, Mock(), None
            )


class TestAndroidScrollGeometry:
    def test_should_limit_scroll_to_screen_boundaries(self):
        from midscene.android.device import calculate_scroll_end_point

        assert calculate_scroll_end_point((100, 100), 0, 500, 1080, 1920) == (
            100,
            600,
        )
        # 20px of room is used as-is; the 50px floor only applies when there
        # is at least that much travel available.
        assert calculate_scroll_end_point((100, 1900), 0, 500, 1080, 1920) == (
            100,
            1920,
        )
        # A short request is kept as-is; the upstream 50px floor only bounds the
        # available-space clamp, it does not grow the requested travel.
        assert calculate_scroll_end_point((100, 100), 0, 30, 1080, 1920) == (
            100,
            130,
        )
        assert calculate_scroll_end_point((1000, 100), 500, 0, 1080, 1920) == (
            1080,
            100,
        )

    def test_rejects_a_scroll_with_no_space(self):
        from midscene.android.device import calculate_scroll_end_point

        with pytest.raises(ValueError, match="finite and inside the viewport"):
            calculate_scroll_end_point((-1, 10), 0, 100, 1080, 1920)
        with pytest.raises(ValueError, match="too small to move"):
            calculate_scroll_end_point((10, 10), 0, 0, 1080, 1920)
        with pytest.raises(ValueError, match="No space to scroll"):
            calculate_scroll_end_point((100, 1920), 0, 500, 1080, 1920)
        with pytest.raises(ValueError, match="No space to scroll"):
            calculate_scroll_end_point((0, 100), -500, 0, 1080, 1920)

    @pytest.mark.asyncio
    async def test_scroll_up_with_start_point_should_call_drag_point_with_calculated_end_point(
        self,
    ):
        from midscene.android.device import AndroidDevice
        from midscene.core.types import Size

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = True
        device.device_id = "emulator-5554"
        device._screen_size = Size(width=1080, height=1920)
        device._physical_size = None
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        # scroll up reveals upper content, so the finger travels down
        await device.scroll("up", distance=500, point=(100, 100))
        assert commands == [
            [
                "-s",
                "emulator-5554",
                "shell",
                "input",
                "swipe",
                "100",
                "100",
                "100",
                "600",
                "1000",
            ]
        ]

    @pytest.mark.asyncio
    async def test_scroll_until_bottom_repeats_the_corrected_boundary_gesture(self):
        from midscene.android.device import AndroidDevice
        from midscene.core.types import Size

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = True
        device.device_id = "emulator-5554"
        device._screen_size = Size(width=1080, height=1920)
        device._physical_size = None
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        with patch("midscene.android.device.asyncio.sleep", AsyncMock()):
            await device.scroll(
                "down", scroll_type="scrollToBottom", point=(100, 100)
            )
        assert len(commands) == 10
        # scroll down reveals lower content: the finger travels up to y=0
        assert all(
            cmd[5:10] == ["100", "100", "100", "0", "100"] for cmd in commands
        )

    @pytest.mark.asyncio
    async def test_should_warn_when_explicit_scroll_down_distance_exceeds_the_swipe_boundary(
        self,
    ):
        from loguru import logger as loguru_logger

        from midscene.android.device import AndroidDevice
        from midscene.core.types import Size

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = True
        device.device_id = "emulator-5554"
        device._screen_size = Size(width=1080, height=1920)
        device._physical_size = None

        async def fake_run(cmd):
            return ""

        device._run_adb_command = fake_run
        messages: List[str] = []
        handler = loguru_logger.add(
            lambda message: messages.append(message.record["message"]),
            level="WARNING",
        )
        try:
            # scroll down reveals lower content, so the finger travels up.
            await device.scroll("down", distance=1500, point=(100, 100))
        finally:
            loguru_logger.remove(handler)

        warning = next(m for m in messages if "clamped" in m)
        assert "scroll to the bottom, use scrollToBottom" in warning

    @pytest.mark.asyncio
    async def test_scroll_until_top_repeats_the_corrected_boundary_gesture(self):
        from midscene.android.device import AndroidDevice
        from midscene.core.types import Size

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = True
        device.device_id = "emulator-5554"
        device._screen_size = Size(width=1080, height=1920)
        device._physical_size = None
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        with patch("midscene.android.device.asyncio.sleep", AsyncMock()):
            await device.scroll("up", scroll_type="scrollToTop")
        assert len(commands) == 10
        # finger travels down from the upper quarter to the bottom edge
        assert commands[0][6] == "480"
        assert commands[0][8] == "1920"


async def _swipe_locate_fn(locate):
    return {"center": {"a": (200, 150), "b": (200, -50)}[locate["prompt"]]}


class TestAndroidGestures:
    def test_android_action_space(self):
        from midscene.core.device import build_android_action_space

        names = {action.name for action in build_android_action_space()}
        assert {
            "Tap",
            "Swipe",
            "LongPress",
            "DragAndDrop",
            "AndroidBackButton",
            "AndroidHomeButton",
            "AndroidRecentAppsButton",
        } <= names


    @pytest.mark.asyncio
    async def test_drag_and_drop_resolves_both_points(self):
        from midscene.core.device import _execute_drag_and_drop

        class DragDevice:
            def __init__(self):
                self.calls = []

            async def drag_and_drop(self, from_point, to_point):
                self.calls.append((tuple(from_point), tuple(to_point)))

        async def locate_fn(locate_param):
            x = 300 if "zone" in locate_param["prompt"] else 100
            return {"center": (x, 50), "rect": None, "description": "x"}

        device = DragDevice()
        await _execute_drag_and_drop(
            {"from": {"prompt": "the card"}, "to": {"prompt": "the drop zone"}},
            device,
            locate_fn,
        )
        assert device.calls == [((100, 50), (300, 50))]


    @pytest.mark.asyncio
    async def test_drag_and_drop_requires_primitive(self):
        from midscene.core.device import _execute_drag_and_drop

        class NoDrag:
            pass

        with pytest.raises(NotImplementedError):
            await _execute_drag_and_drop(
                {"from": {"prompt": "a"}, "to": {"prompt": "b"}}, NoDrag(), None
            )


    @pytest.mark.asyncio
    async def test_android_drag_and_drop_uses_swipe(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = False
        calls = []

        async def swipe(start_x, start_y, end_x, end_y, duration=300, distance=None):
            calls.append((start_x, start_y, end_x, end_y, duration))

        device.swipe = swipe
        await device.drag_and_drop((10, 20), (30, 40))
        assert calls == [(10, 20, 30, 40, 1000)]


    def test_android_action_space_includes_pinch(self):
        from midscene.core.device import build_action_space_for

        android = [a.name for a in build_action_space_for("android")]
        assert android.count("Pinch") == 1
        harmony = [a.name for a in build_action_space_for("harmony")]
        assert "Pinch" not in harmony


    @pytest.mark.asyncio
    async def test_android_pinch_uses_yadb(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("emulator-5554")
        commands: List[list] = []

        async def record(command):
            commands.append(command)
            return ""

        async def no_yadb():
            return None

        monkeypatch.setattr(device, "_ensure_yadb", no_yadb)
        monkeypatch.setattr(device, "_run_adb_command", record)

        await device.pinch([100, 200], 300, 500, duration=700)
        assert commands[-1][-6:] == [
            "-pinch", "100", "200", "300", "500", "700"
        ]

    @pytest.mark.asyncio
    async def test_android_pinch_rejects_non_default_display(self):
        from midscene.android.device import AndroidDevice, AndroidDeviceConfig

        device = AndroidDevice(
            "d", AndroidDeviceConfig(device_id="d", display_id=2)
        )
        with pytest.raises(RuntimeError, match="non-default display"):
            await device.pinch([1, 2], 10, 20)


class _RecordingPullDevice:
    def __init__(self):
        self.calls: List[tuple] = []

    async def pull_gesture(self, direction, start_point=None, distance=None, duration=None):
        self.calls.append((direction, start_point, distance, duration))


class TestPullGesture:
    def test_android_action_space_exposes_pull_gesture(self):
        from midscene.core.device import build_action_space_for

        action = next(
            a for a in build_action_space_for("android") if a.name == "PullGesture"
        )
        assert action.primitive == "pull_gesture"
        assert action.locate_fields == ["locate"]
        assert action.param_schema["direction"]["type"] == '"up" | "down"'
        assert action.sample["direction"] == "down"
        assert "PullGesture" not in [
            a.name for a in build_action_space_for("web")
        ]

    @pytest.mark.asyncio
    async def test_executor_resolves_locate_and_forwards_params(self):
        from midscene.core.device import _execute_pull_gesture

        device = _RecordingPullDevice()
        await _execute_pull_gesture(
            {
                "direction": "up",
                "locate": {"prompt": "a"},
                "distance": 120,
                "duration": 400,
            },
            device,
            _swipe_locate_fn,
        )
        assert device.calls == [("up", [200.0, 150.0], 120, 400)]

    @pytest.mark.asyncio
    async def test_executor_rejects_unknown_direction(self):
        from midscene.core.device import _execute_pull_gesture

        with pytest.raises(ValueError, match="direction"):
            await _execute_pull_gesture(
                {"direction": "left"}, _RecordingPullDevice(), _swipe_locate_fn
            )

    @pytest.mark.asyncio
    async def test_android_defaults_match_upstream(self, monkeypatch):
        from midscene.android.device import AndroidDevice
        from midscene.core.types import Size

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr("midscene.android.device.asyncio.sleep", _no_sleep)
        device = AndroidDevice("emulator-5554")
        device._screen_size = Size(width=1000, height=2000)
        swipes: List[tuple] = []

        async def record_swipe(*args, **kwargs):
            swipes.append((args, kwargs))

        monkeypatch.setattr(device, "swipe", record_swipe)

        await device.pull_gesture("down")
        # 15% start, 50% travel, 800ms default.
        assert swipes[-1] == (((500, 300, 500, 1300)), {"duration": 800})

        await device.pull_gesture("up")
        # 85% start, 40% travel, 600ms default.
        assert swipes[-1] == (((500, 1700, 500, 900)), {"duration": 600})

        await device.pull_gesture("up", start_point=(100, 1700), distance=500, duration=400)
        assert swipes[-1] == (((100, 1700, 100, 1200)), {"duration": 400})

        with pytest.raises(ValueError, match="Unknown pull direction"):
            await device.pull_gesture("left")
