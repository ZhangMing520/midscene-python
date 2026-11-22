"""Unit tests for the Android scrcpy subsystem.

No real device, adb, ffmpeg or network is used: ADB/ffmpeg calls are mocked and
the video stream is a tiny in-memory H.264 packet pipeline.
"""

import asyncio
import base64
import struct
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from midscene.android.device import AndroidDevice, AndroidDeviceConfig
from midscene.android.scrcpy_device_adapter import (
    ScrcpyDeviceAdapter,
    format_scrcpy_fresh_frame_failure,
)
from midscene.android.scrcpy_manager import (
    DEFAULT_SERVER_PATH,
    MAX_VIDEO_BIT_RATE,
    SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE,
    DeviceClockCalibration,
    RawKeyframe,
    ScrcpyFreshFrameUnavailableError,
    ScrcpyScreenshotManager,
    detect_h264_keyframe,
    ensure_scrcpy_server,
    get_scrcpy_server_download_url,
    is_scrcpy_fresh_frame_unavailable_error,
    parse_device_uptime_ms,
    resolve_scrcpy_frame_rate,
    should_download_scrcpy_server,
)

# ---------------------------------------------------------------------------
# Tiny H.264 / JPEG fixtures
# ---------------------------------------------------------------------------

SPS_PACKET = b"\x00\x00\x00\x01\x67\xaa"


def _idr(tag: int) -> bytes:
    return bytes([0x00, 0x00, 0x00, 0x01, 0x65, tag])


def _jpeg_frame(width: int = 1, height: int = 1) -> bytes:
    return bytes(
        [
            0xFF,
            0xD8,
            0xFF,
            0xC0,
            0x00,
            0x11,
            0x08,
            (height >> 8) & 0xFF,
            height & 0xFF,
            (width >> 8) & 0xFF,
            width & 0xFF,
            0x03,
            0x01,
            0x11,
            0x00,
            0x02,
            0x11,
            0x00,
            0x03,
            0x11,
            0x00,
            0xFF,
            0xD9,
        ]
    )


def _video_header(width: int = 1080, height: int = 1920) -> bytes:
    return (
        b"fake-device".ljust(64, b"\x00")
        + b"h264"
        + struct.pack(">II", width, height)
    )


def _config_packet(data: bytes = SPS_PACKET) -> bytes:
    return struct.pack(">QI", 0xFFFFFFFFFFFFFFFF, len(data)) + data


def _data_packet(data: bytes, pts: int) -> bytes:
    return struct.pack(">QI", pts, len(data)) + data


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = None
        self.stderr = None
        self.returncode = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeBackend:
    """Duck-typed stand-in for AdbCommandBackend."""

    def __init__(self, clock_output: str = "mLastWakeTime=2000 (now)") -> None:
        self.device_id = "fake-device"
        self.adb_path = "adb"
        self.clock_output = clock_output
        self.pushed = []
        self.forwards = []
        self.removed = []
        self.server_args = None
        self.process = FakeProcess()
        self.closed = False

    async def push(self, local_path: str, remote_path: str) -> None:
        self.pushed.append((local_path, remote_path))

    async def shell_text(self, args):
        assert args == ["dumpsys", "power"]
        return self.clock_output

    async def forward_tcp(self, remote_socket: str) -> int:
        self.forwards.append(remote_socket)
        return 4711

    async def remove_forward(self, local_port: int) -> None:
        self.removed.append(local_port)

    async def start_server(self, args):
        self.server_args = args
        return self.process

    async def screencap_png(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"fallback"

    async def screen_size(self):
        return {"width": 1080, "height": 1920}

    async def close(self) -> None:
        self.closed = True


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before the timeout")


async def _connected_manager(
    backend: FakeBackend,
    payload: bytes,
    jpeg=None,
) -> ScrcpyScreenshotManager:
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    writer = FakeWriter()

    async def connection_factory(host, port):
        return reader, writer

    manager = ScrcpyScreenshotManager(
        backend,
        backend.push,
        {"idle_timeout_ms": 0},
        connection_factory=connection_factory,
    )
    manager.resolve_server_bin_path = lambda: "/tmp/fake-scrcpy-server"
    manager._decode_h264_to_jpeg = AsyncMock(
        return_value=jpeg if jpeg is not None else _jpeg_frame(1, 1)
    )
    await manager.ensure_connected()
    return manager


# ---------------------------------------------------------------------------
# Configuration / validation
# ---------------------------------------------------------------------------

class TestResolveScrcpyFrameRate:
    def test_accepts_none_and_positive_integers(self):
        assert resolve_scrcpy_frame_rate(None) is None
        assert resolve_scrcpy_frame_rate(30) == 30
        assert resolve_scrcpy_frame_rate(30.0) == 30
        assert resolve_scrcpy_frame_rate(2_147_483_647) == 2_147_483_647

    @pytest.mark.parametrize(
        "value", [0, -1, 1.5, float("nan"), float("inf"), 2_147_483_648, "10", True]
    )
    def test_rejects_invalid_values(self, value):
        with pytest.raises(ValueError, match="Invalid scrcpyConfig.frameRate"):
            resolve_scrcpy_frame_rate(value)


class TestAdapterConfig:
    def test_defaults_and_disabled_by_default(self):
        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.is_enabled() is False
        config = adapter.resolve_config()
        assert config.enabled is False
        assert config.max_size == 0
        assert config.idle_timeout_ms == 30_000
        assert config.video_bit_rate == 100_000_000
        assert config.video_reset_frame_timeout_ms == 800
        assert config.frame_rate is None

    def test_accepts_snake_and_camel_case_keys(self):
        snake = ScrcpyDeviceAdapter(
            "device",
            {
                "enabled": True,
                "frame_rate": 30,
                "max_size": 1024,
                "video_bit_rate": 8_000_000,
                "idle_timeout_ms": 60_000,
                "video_reset_frame_timeout_ms": 1200,
            },
        ).resolve_config()
        camel = ScrcpyDeviceAdapter(
            "device",
            {
                "enabled": True,
                "frameRate": 30,
                "maxSize": 1024,
                "videoBitRate": 8_000_000,
                "idleTimeoutMs": 60_000,
                "videoResetFrameTimeoutMs": 1200,
            },
        ).resolve_config()
        assert snake == camel
        assert snake.frame_rate == 30
        assert snake.maxSize == 1024
        assert snake.videoResetFrameTimeoutMs == 1200

    @pytest.mark.parametrize(
        "max_size", [-1, 1.5, float("inf"), float("nan"), "10"]
    )
    def test_rejects_invalid_max_size(self, max_size):
        adapter = ScrcpyDeviceAdapter("device", {"maxSize": max_size})
        with pytest.raises(
            ValueError,
            match="Invalid scrcpyConfig.maxSize: expected a non-negative integer",
        ):
            adapter.resolve_config()

    @pytest.mark.parametrize(
        "timeout", [0, -1, 1.5, float("inf"), float("nan"), "10"]
    )
    def test_rejects_invalid_video_reset_timeout(self, timeout):
        adapter = ScrcpyDeviceAdapter(
            "device", {"videoResetFrameTimeoutMs": timeout}
        )
        with pytest.raises(
            ValueError,
            match=(
                "Invalid scrcpyConfig.videoResetFrameTimeoutMs: expected a "
                "positive integer"
            ),
        ):
            adapter.resolve_config()

    def test_rejects_invalid_frame_rate_during_resolution(self):
        adapter = ScrcpyDeviceAdapter("device", {"frameRate": -1})
        with pytest.raises(ValueError, match="Invalid scrcpyConfig.frameRate"):
            adapter.resolve_config()

    def test_caches_resolved_config(self):
        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.resolve_config() is adapter.resolve_config()


# ---------------------------------------------------------------------------
# Freshness error contract
# ---------------------------------------------------------------------------

class TestFreshFrameFailure:
    def test_formats_freshness_target_without_prescribing_a_bitrate(self):
        error = ScrcpyFreshFrameUnavailableError(
            "stale",
            failure_kind="freshness-target",
            timeout_ms=300,
            video_bit_rate=100_000_000,
        )
        message = format_scrcpy_fresh_frame_failure(error)
        assert "does not by itself identify bandwidth" in message
        assert "Current videoBitRate: 100000000 bps (100 Mbps)." in message
        assert "lower" not in message.lower()

    def test_formats_stream_startup_failure(self):
        error = ScrcpyFreshFrameUnavailableError(
            "startup",
            failure_kind="stream-startup",
            timeout_ms=5_000,
            video_bit_rate=4_000_000,
        )
        message = format_scrcpy_fresh_frame_failure(error)
        assert "stream startup or encoder-readiness failure" in message
        assert "5000ms" in message

    def test_predicate_accepts_class_and_duck_typed_errors(self):
        error = ScrcpyFreshFrameUnavailableError(
            "stale",
            failure_kind="freshness-target",
            timeout_ms=300,
            video_bit_rate=1,
        )
        assert is_scrcpy_fresh_frame_unavailable_error(error) is True

        class CrossModuleError(Exception):
            code = SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE

        assert is_scrcpy_fresh_frame_unavailable_error(CrossModuleError()) is True
        assert is_scrcpy_fresh_frame_unavailable_error(RuntimeError("x")) is False


# ---------------------------------------------------------------------------
# Manager prerequisites / options
# ---------------------------------------------------------------------------

class TestManagerPrerequisites:
    @pytest.mark.asyncio
    async def test_fails_when_ffmpeg_is_missing(self):
        manager = ScrcpyScreenshotManager(FakeBackend(), None, {})
        with patch.object(
            manager, "check_ffmpeg_available", new=AsyncMock(return_value=False)
        ):
            with pytest.raises(RuntimeError, match="ffmpeg is not available"):
                await manager.validate_environment()

    @pytest.mark.asyncio
    async def test_fails_when_server_jar_is_missing(self):
        manager = ScrcpyScreenshotManager(FakeBackend(), None, {})
        with patch.object(
            manager, "check_ffmpeg_available", new=AsyncMock(return_value=True)
        ), patch(
            "midscene.android.scrcpy_manager.ensure_scrcpy_server",
            side_effect=FileNotFoundError("missing scrcpy jar"),
        ):
            with pytest.raises(FileNotFoundError, match="missing scrcpy jar"):
                await manager.validate_environment()

    @pytest.mark.asyncio
    async def test_caches_ffmpeg_check(self):
        manager = ScrcpyScreenshotManager(FakeBackend(), None, {})
        check = AsyncMock(return_value=True)
        with patch.object(manager, "check_ffmpeg_available", new=check), patch(
            "midscene.android.scrcpy_manager.ensure_scrcpy_server",
            return_value="/tmp/scrcpy-server",
        ):
            await manager.validate_environment()
            await manager.validate_environment()
        check.assert_awaited_once()


class TestManagerOptions:
    def test_defaults_and_bitrate_clamp(self):
        manager = ScrcpyScreenshotManager(FakeBackend(), None, {})
        assert manager.options.max_size == 0
        assert manager.options.video_bit_rate == 100_000_000
        assert manager.options.idle_timeout_ms == 30_000
        assert manager.options.video_reset_frame_timeout_ms == 800

        clamped = ScrcpyScreenshotManager(
            FakeBackend(), None, {"videoBitRate": 500_000_000}
        )
        assert clamped.options.video_bit_rate == MAX_VIDEO_BIT_RATE

    def test_create_scrcpy_options_only_adds_explicit_frame_rate(self):
        default = ScrcpyScreenshotManager(
            FakeBackend(), None, {}
        ).create_scrcpy_options()
        assert default["video_codec_options"] == (
            "i-frame-interval=0,bitrate-mode=2,repeat-previous-frame-after=0"
        )
        assert default["max_fps"] == 10
        assert default["send_frame_meta"] is True
        assert default["tunnel_forward"] is True
        assert default["audio"] is False

        custom = ScrcpyScreenshotManager(
            FakeBackend(), None, {"frameRate": 30}
        ).create_scrcpy_options()
        assert custom["video_codec_options"].endswith(",frame-rate=30")
        assert custom["max_fps"] == default["max_fps"]


# ---------------------------------------------------------------------------
# scrcpy-server acquisition
# ---------------------------------------------------------------------------

class TestEnsureScrcpyServer:
    def test_download_url_and_version_helpers(self):
        assert get_scrcpy_server_download_url("v3.3.3") == (
            "https://github.com/Genymobile/scrcpy/releases/download/"
            "v3.3.3/scrcpy-server-v3.3.3"
        )
        assert should_download_scrcpy_server(None, "v3.3.3") is True
        assert should_download_scrcpy_server("v3.3.4", "v3.3.3") is True
        assert should_download_scrcpy_server(" v3.3.3\n", "v3.3.3") is False

    def test_uses_cached_jar_without_downloading(self, tmp_path):
        jar = tmp_path / "scrcpy-server"
        jar.write_bytes(b"jar")
        assert ensure_scrcpy_server(cache_dir=str(tmp_path)) == str(jar)

    def test_explicit_missing_jar_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="was not found"):
            ensure_scrcpy_server(explicit_path=str(tmp_path / "missing.jar"))

    def test_downloads_into_cache_directory(self, tmp_path):
        cache_dir = tmp_path / "cache"
        calls = []

        def http_get(url, timeout):
            calls.append((url, timeout))
            return b"downloaded-jar"

        path = ensure_scrcpy_server(
            cache_dir=str(cache_dir), http_get=http_get
        )
        assert Path(path).read_bytes() == b"downloaded-jar"
        assert (cache_dir / "scrcpy-server.version").read_text().strip() == (
            "v3.3.3"
        )
        assert calls[0][0].endswith("scrcpy-server-v3.3.3")

    def test_accepts_single_argument_download_callable(self, tmp_path):
        cache_dir = tmp_path / "cache"
        path = ensure_scrcpy_server(
            cache_dir=str(cache_dir), http_get=lambda url: b"jar"
        )
        assert Path(path).read_bytes() == b"jar"


# ---------------------------------------------------------------------------
# H.264 helpers / device clock
# ---------------------------------------------------------------------------

class TestH264AndClockHelpers:
    def test_detects_keyframe_nal_types(self):
        assert detect_h264_keyframe(_idr(1)) is True
        assert detect_h264_keyframe(SPS_PACKET) is True
        # 4-byte start code + non-keyframe NAL type (0x41 & 0x1f == 1)
        assert detect_h264_keyframe(b"\x00\x00\x00\x01\x41\x01") is False
        assert detect_h264_keyframe(b"") is False

    def test_parses_device_uptime_formats(self):
        assert (
            parse_device_uptime_ms("  mLastWakeTime=324781136 (228676 ms ago)\n")
            == 325009812
        )
        assert parse_device_uptime_ms("mLastWakeTime=1000 (in 200 ms)") == 800
        assert parse_device_uptime_ms("mLastWakeTime=1000 (now)") == 1000
        with pytest.raises(ValueError, match="Unable to read Android device uptime"):
            parse_device_uptime_ms("no uptime here")


# ---------------------------------------------------------------------------
# Manager frame pipeline / decode
# ---------------------------------------------------------------------------

class TestManagerPipeline:
    @pytest.mark.asyncio
    async def test_reads_keyframes_and_decodes_with_mocked_ffmpeg(self):
        backend = FakeBackend()
        decoded = _jpeg_frame(1080, 1920)
        payload = (
            _video_header(1080, 1920)
            + _config_packet()
            + _data_packet(_idr(0x01), 2_000_000)
        )
        manager = await _connected_manager(backend, payload, decoded)

        await _wait_until(
            lambda: manager.get_latest_raw_keyframe() is not None
        )
        frame = manager.get_latest_raw_keyframe()
        assert isinstance(frame, RawKeyframe)
        assert frame.data == _idr(0x01)
        assert frame.header == SPS_PACKET

        jpeg = await manager.decode_raw_keyframe_to_jpeg(frame)
        assert jpeg == decoded
        assert manager.get_resolution() == {"width": 1080, "height": 1920}

        raw_base64 = await manager.screenshot()
        assert raw_base64 == base64.b64encode(decoded).decode("ascii")

        assert backend.pushed == [
            ("/tmp/fake-scrcpy-server", DEFAULT_SERVER_PATH)
        ]
        assert backend.forwards and backend.forwards[0].startswith("scrcpy_")
        assert "send_frame_meta=true" in backend.server_args
        assert "CLASSPATH=" + DEFAULT_SERVER_PATH in backend.server_args

        await manager.dispose()
        assert backend.removed == [4711]
        assert backend.closed is True

    @pytest.mark.asyncio
    async def test_barrier_rejects_pre_action_frames(self):
        manager = ScrcpyScreenshotManager(FakeBackend(), None, {})
        manager._device_clock_calibration = DeviceClockCalibration(
            device_uptime_us=1_000_000,
            host_monotonic_us=10_000_000,
            host_wall_time_ms=2_000,
            round_trip_us=10_000,
        )
        manager._monotonic_time_us = lambda: 10_000_000
        manager._sps_header = b"header"

        barrier = await manager.set_freshness_barrier("completed input action")
        assert barrier == 1_006_000

        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(_idr(0x01), 1_005_999)
        assert manager.get_latest_raw_keyframe() is None

        manager._process_packet(_idr(0x02), 1_006_000)
        latest = manager.get_latest_raw_keyframe()
        assert latest is not None
        assert latest.data == _idr(0x02)

    @pytest.mark.asyncio
    async def test_screenshot_raises_freshness_error_when_no_frame_crosses(self):
        backend = FakeBackend()
        payload = _video_header() + _config_packet()
        manager = await _connected_manager(backend, payload)
        # Only a configuration packet arrives; the startup window expires.
        manager._stream_startup_window = {"deadline_at": 0}
        manager._monotonic_time_us = lambda: 10_000_000
        manager._device_clock_calibration = DeviceClockCalibration(
            device_uptime_us=2_000_000,
            host_monotonic_us=10_000_000,
            host_wall_time_ms=2_000,
            round_trip_us=10_000,
        )
        manager._wait_for_next_keyframe = AsyncMock(
            side_effect=RuntimeError("no frame")
        )

        with pytest.raises(ScrcpyFreshFrameUnavailableError) as excinfo:
            await manager.get_screenshot_jpeg()
        assert excinfo.value.failure_kind == "freshness-target"
        assert excinfo.value.timeout_ms == 300
        assert manager.is_connected() is False


# ---------------------------------------------------------------------------
# Adapter lifecycle / fallback / status
# ---------------------------------------------------------------------------

class FakeManager:
    def __init__(self) -> None:
        self.connected = False
        self.disposed = False
        self.barriers = []
        self.screenshot_results = []
        self.screenshot_calls = 0
        self.resolution = {"width": 1080, "height": 1920}
        self.listeners = []
        self.validate_calls = 0

    async def validate_environment(self) -> None:
        self.validate_calls += 1

    async def ensure_connected(self) -> None:
        self.connected = True

    async def ensure_frame_clock_calibration(self) -> None:
        return None

    def is_connected(self) -> bool:
        return self.connected

    async def get_screenshot_jpeg(self) -> bytes:
        self.screenshot_calls += 1
        result = (
            self.screenshot_results.pop(0)
            if self.screenshot_results
            else _jpeg_frame()
        )
        if isinstance(result, BaseException):
            raise result
        return result

    async def set_freshness_barrier(self, reason, options=None) -> int:
        self.barriers.append((reason, options))
        return 1

    def subscribe_keyframes(self, listener):
        self.listeners.append(listener)
        return lambda: None

    def get_latest_raw_keyframe(self):
        return None

    async def decode_raw_keyframe_to_jpeg(self, frame):
        return _jpeg_frame()

    def get_resolution(self):
        return self.resolution

    async def dispose(self) -> None:
        self.disposed = True
        self.connected = False


def _adapter(config=None, manager=None, backend=None, now=None):
    backend = backend or FakeBackend()
    manager = manager or FakeManager()
    adapter = ScrcpyDeviceAdapter(
        "device",
        config,
        lambda: backend,
        manager_factory=lambda resolved_backend, options: manager,
        now_ms=now or (lambda: 1_000_000.0),
    )
    return adapter, manager, backend


class TestScrcpyDeviceAdapter:
    @pytest.mark.asyncio
    async def test_disabled_adapter_uses_adb_fallback(self):
        adapter, manager, backend = _adapter(None)
        result = await adapter.screenshot_base64()
        assert result.startswith("data:image/png;base64,")
        assert manager.validate_calls == 0

    @pytest.mark.asyncio
    async def test_initialize_connects_and_clears_failure(self):
        adapter, manager, _ = _adapter({"enabled": True})
        await adapter.initialize()
        assert manager.validate_calls == 1
        assert manager.connected is True
        assert adapter.get_status().connected is True
        assert adapter.get_status().last_error is None

    @pytest.mark.asyncio
    async def test_generic_failure_falls_back_and_starts_cooldown(self):
        now = [1_000_000.0]
        adapter, manager, _ = _adapter(
            {"enabled": True}, now=lambda: now[0]
        )
        manager.screenshot_results = [RuntimeError("codec not ready")]

        result = await adapter.screenshot_base64(fallback=lambda: "adbfallback")
        assert result == "adbfallback"
        status = adapter.get_status()
        assert status.last_error is not None
        assert "codec not ready" in status.last_error
        assert status.retry_after == 1_005_000
        assert adapter.is_enabled() is False

        now[0] += 6_000
        assert adapter.is_enabled() is True
        recovered = await adapter.screenshot_base64()
        assert recovered.startswith("data:image/jpeg;base64,")
        assert adapter.get_status().last_error is None

    @pytest.mark.asyncio
    async def test_freshness_failure_restarts_the_stream_once(self):
        adapter, manager, _ = _adapter({"enabled": True})
        error = ScrcpyFreshFrameUnavailableError(
            "stale",
            failure_kind="freshness-target",
            timeout_ms=300,
            video_bit_rate=100_000_000,
        )
        manager.screenshot_results = [error, _jpeg_frame(2, 3)]

        result = await adapter.screenshot_base64()
        assert manager.screenshot_calls == 2
        assert result.startswith("data:image/jpeg;base64,")
        assert adapter.get_status().last_error is None

    @pytest.mark.asyncio
    async def test_freshness_failure_after_restart_falls_back(self):
        adapter, manager, _ = _adapter({"enabled": True})
        first = ScrcpyFreshFrameUnavailableError(
            "stale",
            failure_kind="freshness-target",
            timeout_ms=300,
            video_bit_rate=1,
        )
        second = ScrcpyFreshFrameUnavailableError(
            "still stale",
            failure_kind="freshness-target",
            timeout_ms=300,
            video_bit_rate=1,
        )
        manager.screenshot_results = [first, second]

        result = await adapter.screenshot_base64(fallback=lambda: "adb")
        assert result == "adb"
        assert manager.screenshot_calls == 2
        assert adapter.get_status().retry_after is not None

    @pytest.mark.asyncio
    async def test_mark_action_barrier_and_status(self):
        adapter, manager, _ = _adapter({"enabled": True})
        adapter._manager = manager
        manager.connected = True
        adapter._monotonic_time_us_fn = lambda: 10_100_000

        await adapter.mark_action_barrier()
        assert manager.barriers == [
            ("completed input action", {"host_monotonic_us": 10_100_000})
        ]

    def test_size_and_scaling_ratio(self):
        adapter, manager, _ = _adapter({"enabled": True})
        assert adapter.get_size() is None
        manager.resolution = {"width": 540, "height": 960}
        adapter._manager = manager
        assert adapter.get_size() == {"width": 540, "height": 960}
        assert adapter.get_scaling_ratio(1080) == 0.5

    @pytest.mark.asyncio
    async def test_size_falls_back_to_adb_backend(self):
        adapter, _manager, backend = _adapter({"enabled": True})
        assert await adapter.size() == {"width": 1080, "height": 1920}

    @pytest.mark.asyncio
    async def test_disconnect_disposes_manager(self):
        adapter, manager, _ = _adapter({"enabled": True})
        await adapter.initialize()
        await adapter.disconnect()
        assert manager.disposed is True
        assert adapter._manager is None


# ---------------------------------------------------------------------------
# AndroidDevice integration (opt-in, default off)
# ---------------------------------------------------------------------------

class TestAndroidDeviceIntegration:
    def test_scrcpy_is_disabled_by_default(self):
        device = AndroidDevice("device")
        assert device.config.scrcpy_config is None
        assert device._scrcpy_configured() is False

    @pytest.mark.asyncio
    async def test_enabled_device_uses_scrcpy_screenshot_and_size(self):
        device = AndroidDevice(
            "device",
            AndroidDeviceConfig(
                device_id="device", scrcpy_config={"enabled": True}
            ),
        )

        class FakeAdapter:
            def is_enabled(self):
                return True

            async def screenshot_base64(self, device_info=None):
                return "data:image/jpeg;base64,abc"

            def get_size(self, device_info=None):
                return {"width": 10, "height": 20}

        device._scrcpy_adapter = FakeAdapter()
        assert await device._take_screenshot() == "abc"
        assert await device.size() == {"width": 10, "height": 20}

    @pytest.mark.asyncio
    async def test_scrcpy_failure_falls_back_to_adb_screencap(self):
        device = AndroidDevice(
            "device",
            AndroidDeviceConfig(
                device_id="device", scrcpy_config={"enabled": True}
            ),
        )

        class FailingAdapter:
            def is_enabled(self):
                return True

            async def screenshot_base64(self, device_info=None):
                raise RuntimeError("scrcpy broke")

        device._scrcpy_adapter = FailingAdapter()
        png = b"\x89PNG\r\n\x1a\nadb"
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=png, stderr=b""
        )

        with patch.object(
            AndroidDevice, "_run_adb_command", new=AsyncMock(return_value=completed)
        ):
            result = await device._take_screenshot()

        assert result == base64.b64encode(png).decode("ascii")

    @pytest.mark.asyncio
    async def test_disabled_device_still_uses_adb_screencap(self):
        device = AndroidDevice("device")
        assert device._scrcpy_configured() is False
        png = b"\x89PNG\r\n\x1a\nadb"
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=png, stderr=b""
        )

        with patch.object(
            AndroidDevice, "_run_adb_command", new=AsyncMock(return_value=completed)
        ):
            result = await device._take_screenshot()

        assert result == base64.b64encode(png).decode("ascii")
        assert device._scrcpy_adapter is None
