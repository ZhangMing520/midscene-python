"""Port of upstream packages/android/tests/unit-test/scrcpy-manager.test.ts."""

import asyncio
import struct
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, Mock

import pytest

from midscene.android import scrcpy_manager as sm
from midscene.android.scrcpy_manager import (
    DEFAULT_SERVER_PATH,
    MAX_VIDEO_BIT_RATE,
    DeviceClockCalibration,
    RawKeyframe,
    ScrcpyFreshFrameUnavailableError,
    ScrcpyScreenshotManager,
    parse_device_uptime_ms,
)

SPS_PACKET = bytes([0x00, 0x00, 0x00, 0x01, 0x67, 0xAA])


def idr_frame(tag: int) -> bytes:
    return bytes([0x00, 0x00, 0x00, 0x01, 0x65, tag])


def jpeg_frame(width: int = 1, height: int = 1) -> bytes:
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


def video_header(width: int = 1080, height: int = 1920) -> bytes:
    return (
        b"fake-device".ljust(64, b"\x00") + b"h264" + struct.pack(">II", width, height)
    )


def calibration(
    device_uptime_us=1_000_000,
    host_monotonic_us=10_000_000,
    host_wall_time_ms=2_000,
    round_trip_us=10_000,
):
    return DeviceClockCalibration(
        device_uptime_us=device_uptime_us,
        host_monotonic_us=host_monotonic_us,
        host_wall_time_ms=host_wall_time_ms,
        round_trip_us=round_trip_us,
    )


async def _noop_push(local_path, remote_path):
    return None


def create_manager(adb=None, options=None, push_server=None):
    return ScrcpyScreenshotManager(
        adb if adb is not None else {},
        push_server if push_server is not None else _noop_push,
        options if options is not None else {},
    )


class FakeWriter:
    def __init__(self):
        self.close_calls = 0
        self.close_error = None

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error

    async def wait_closed(self):
        return None


class RaisingReader:
    def __init__(self, error):
        self.error = error

    async def readexactly(self, size):
        raise self.error


class ClockAdb:
    def __init__(self, output="mLastWakeTime=1000 (50 ms ago)"):
        self.output = output
        self.shell_calls = []

    async def shell_text(self, args):
        self.shell_calls.append(args)
        return self.output


class LineStream:
    def __init__(self, lines):
        self.lines = [f"{line}\n".encode() for line in lines]

    async def readline(self):
        if self.lines:
            return self.lines.pop(0)
        return b""


class FakeProcess:
    def __init__(self, lines):
        self.stdout = LineStream(lines)
        self.stderr = None


class PushBackend:
    def __init__(self):
        self.pushed = []

    async def push(self, local_path, remote_path):
        self.pushed.append((local_path, remote_path))

    async def shell_text(self, args):
        return "mLastWakeTime=2000 (now)"

    async def forward_tcp(self, remote_socket):
        return 4711

    async def start_server(self, args):
        return None

    async def remove_forward(self, local_port):
        return None


def prepare_cached_planning_frame(
    manager,
    *,
    pts_us=2_000_000,
    frame_data=b"fresh-frame",
    round_trip_us=1_544_554,
    reset_video=None,
):
    if reset_video is not None:
        manager._controller = SimpleNamespace(reset_video=reset_video)
    manager._sps_header = b"header"
    manager._last_raw_keyframe = frame_data
    manager._last_raw_keyframe_pts_us = pts_us
    manager._last_raw_keyframe_at = 2000
    manager._last_raw_keyframe_stream_epoch = manager._stream_epoch
    manager._device_clock_calibration = calibration(
        device_uptime_us=2_000_000,
        host_monotonic_us=10_000_000,
        host_wall_time_ms=2_000,
        round_trip_us=round_trip_us,
    )
    manager._monotonic_time_us = lambda: 10_000_000
    manager.ensure_connected = AsyncMock()
    manager._reset_idle_timer = Mock()


def spy_async(obj, name):
    original = getattr(obj, name)
    return mock.patch.object(obj, name, new=AsyncMock(wraps=original))


async def _wait_until(predicate, timeout=1.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condition was not met before the timeout")


class TestValidateEnvironment:
    @pytest.mark.asyncio
    async def test_should_succeed_when_ffmpeg_is_available(self):
        """should succeed when ffmpeg is available."""

        manager = create_manager()
        with (
            mock.patch.object(
                manager, "check_ffmpeg_available", new=AsyncMock(return_value=True)
            ),
            mock.patch.object(
                manager, "resolve_server_bin_path", new=Mock(return_value="/tmp/s")
            ),
        ):
            assert await manager.validate_environment() is None

    @pytest.mark.asyncio
    async def test_should_throw_when_ffmpeg_is_not_available(self):
        """should throw when ffmpeg is not available."""

        manager = create_manager()
        with (
            mock.patch.object(
                manager, "check_ffmpeg_available", new=AsyncMock(return_value=False)
            ),
            mock.patch.object(
                manager, "resolve_server_bin_path", new=Mock(return_value="/tmp/s")
            ),
            pytest.raises(RuntimeError, match="ffmpeg is not available"),
        ):
            await manager.validate_environment()

    @pytest.mark.asyncio
    async def test_should_throw_when_check_ffmpeg_available_throws_an_error(self):
        """should throw when checkFfmpegAvailable throws an error."""

        manager = create_manager()
        with (
            mock.patch.object(
                manager,
                "check_ffmpeg_available",
                new=AsyncMock(side_effect=RuntimeError("unexpected error")),
            ),
            mock.patch.object(
                manager, "resolve_server_bin_path", new=Mock(return_value="/tmp/s")
            ),
            pytest.raises(RuntimeError, match="ffmpeg is not available"),
        ):
            await manager.validate_environment()

    @pytest.mark.asyncio
    async def test_should_cache_ffmpeg_check_result_only_check_once_on_success(self):
        """should cache ffmpeg check result (only check once on success)."""

        manager = create_manager()
        check = AsyncMock(return_value=True)
        with (
            mock.patch.object(manager, "check_ffmpeg_available", new=check),
            mock.patch.object(
                manager, "resolve_server_bin_path", new=Mock(return_value="/tmp/s")
            ),
        ):
            await manager.validate_environment()
            await manager.validate_environment()

        check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_should_be_independent_from_ensure_connected(self):
        """should be independent from ensureConnected."""

        manager = create_manager()
        ensure_connected = AsyncMock()
        with (
            mock.patch.object(
                manager, "check_ffmpeg_available", new=AsyncMock(return_value=True)
            ),
            mock.patch.object(
                manager, "resolve_server_bin_path", new=Mock(return_value="/tmp/s")
            ),
            mock.patch.object(manager, "ensure_connected", new=ensure_connected),
        ):
            await manager.validate_environment()

        ensure_connected.assert_not_awaited()


class TestConstructorDefaults:
    def test_should_use_default_options_when_none_provided(self):
        """should use default options when none provided."""

        options = create_manager().options
        assert options.max_size == 0
        assert options.video_bit_rate == 100_000_000
        assert options.idle_timeout_ms == 30_000

    def test_should_use_provided_options(self):
        """should use provided options."""

        options = create_manager(
            options={
                "maxSize": 1024,
                "videoBitRate": 4_000_000,
                "idleTimeoutMs": 60_000,
            }
        ).options
        assert options.max_size == 1024
        assert options.video_bit_rate == 4_000_000
        assert options.idle_timeout_ms == 60_000

    def test_should_partially_override_defaults(self):
        """should partially override defaults."""

        options = create_manager(options={"maxSize": 512}).options
        assert options.max_size == 512
        assert options.video_bit_rate == 100_000_000
        assert options.idle_timeout_ms == 30_000

    def test_should_clamp_video_bit_rate_to_safe_maximum(self):
        """should clamp videoBitRate to safe maximum."""

        options = create_manager(options={"videoBitRate": 500_000_000}).options
        assert options.video_bit_rate == 100_000_000
        assert options.video_bit_rate == MAX_VIDEO_BIT_RATE


class TestGetResolution:
    def test_should_return_null_when_not_connected(self):
        """should return null when not connected."""

        assert create_manager().get_resolution() is None


class TestIsConnected:
    def test_should_return_false_initially(self):
        """should return false initially."""

        assert create_manager().is_connected() is False


class TestEnsureConnected:
    def test_preserves_the_original_codec_options_and_only_adds_an_explicit_frame_rate(
        self,
    ):
        """preserves the original codec options and only adds an explicit frame rate."""

        options = create_manager().create_scrcpy_options()
        assert options["video_codec_options"] == (
            "i-frame-interval=0,bitrate-mode=2,repeat-previous-frame-after=0"
        )
        assert options["max_fps"] == 10

        custom = create_manager(options={"frameRate": 30}).create_scrcpy_options()
        assert custom["video_codec_options"] == (
            "i-frame-interval=0,bitrate-mode=2,"
            "repeat-previous-frame-after=0,frame-rate=30"
        )
        assert custom["max_fps"] == options["max_fps"]

    @pytest.mark.parametrize(
        "frame_rate",
        [0, -1, 1.5, float("nan"), float("inf"), 2_147_483_648, "10"],
    )
    def test_rejects_invalid_frame_rate(self, frame_rate):
        """rejects invalid frameRate %s."""

        with pytest.raises(ValueError, match="Invalid scrcpyConfig.frameRate"):
            create_manager(options={"frameRate": frame_rate})

    def test_should_use_a_forward_tunnel_with_a_fresh_scrcpy_instance_id(self):
        """should use a forward tunnel with a fresh scrcpy instance id."""

        manager = create_manager(options={"maxSize": 1024, "videoBitRate": 8_000_000})
        first = manager.create_scrcpy_options()
        second = manager.create_scrcpy_options()

        assert first["control"] is True
        assert first["power_on"] is False
        assert first["clipboard_autosync"] is False
        assert first["tunnel_forward"] is True
        assert first["max_size"] == 1024
        assert first["video_bit_rate"] == 8_000_000
        assert first["scid"] is not None
        assert second["scid"] is not None
        assert first["scid"] != second["scid"]

    def test_disables_repeated_frames_so_unchanged_pixels_cannot_acquire_a_fresh_pts(
        self,
    ):
        """disables repeated frames so unchanged pixels cannot acquire a fresh PTS."""

        options = create_manager().create_scrcpy_options()
        assert "repeat-previous-frame-after=0" in options["video_codec_options"]

    @pytest.mark.asyncio
    async def test_uses_the_configured_server_pusher_during_connection(self):
        """uses the configured server pusher during connection."""

        backend = PushBackend()
        push_server = AsyncMock()
        reader = asyncio.StreamReader()
        reader.feed_data(video_header())
        reader.feed_eof()
        writer = FakeWriter()

        async def connection_factory(host, port):
            return reader, writer

        manager = ScrcpyScreenshotManager(
            backend,
            push_server,
            {"idle_timeout_ms": 0},
            connection_factory=connection_factory,
        )
        manager.resolve_server_bin_path = lambda: "/tmp/scrcpy-server"
        manager.ensure_frame_clock_calibration = AsyncMock()

        await manager.ensure_connected()

        push_server.assert_awaited_once_with("/tmp/scrcpy-server", DEFAULT_SERVER_PATH)
        await manager.dispose()

    @pytest.mark.asyncio
    async def test_shares_one_connection_attempt_across_concurrent_callers(self):
        """shares one connection attempt across concurrent callers."""

        manager = create_manager()
        calls = []
        gate = asyncio.Event()

        async def connect():
            calls.append(1)
            await gate.wait()

        with mock.patch.object(manager, "_connect_scrcpy", new=connect):
            first = asyncio.ensure_future(manager.ensure_connected())
            second = asyncio.ensure_future(manager.ensure_connected())
            await _wait_until(lambda: len(calls) == 1)
            assert len(calls) == 1
            gate.set()
            assert await asyncio.gather(first, second) == [None, None]

    @pytest.mark.asyncio
    async def test_should_calibrate_an_already_started_stream_only_once(self):
        """should calibrate an already-started stream only once."""

        manager = create_manager()
        manager._writer = FakeWriter()
        manager._reader = object()
        read_clock = AsyncMock(return_value=calibration())
        with mock.patch.object(
            manager, "_read_device_clock_calibration", new=read_clock
        ):
            assert await manager.ensure_connected() is None
            assert await manager.ensure_connected() is None

        read_clock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shares_a_connection_failure_across_concurrent_callers(self):
        """shares a connection failure across concurrent callers."""

        manager = create_manager()
        connection_error = RuntimeError("codec unavailable")

        async def connect():
            raise connection_error

        with mock.patch.object(manager, "_connect_scrcpy", new=connect):
            first = asyncio.ensure_future(manager.ensure_connected())
            second = asyncio.ensure_future(manager.ensure_connected())
            with pytest.raises(RuntimeError) as first_error:
                await first
            with pytest.raises(RuntimeError) as second_error:
                await second

        assert first_error.value is connection_error
        assert second_error.value is connection_error

    def test_should_include_client_and_server_output_in_connection_errors(self):
        """should include client and server output in connection errors."""

        manager = create_manager()
        error = RuntimeError("ExactReadable ended")
        error.output = ["server exited before metadata"]

        result = manager._create_connection_error(
            error,
            ["java.lang.IllegalStateException: codec not ready"],
        )

        assert "ExactReadable ended" in str(result)
        assert "server exited before metadata" in str(result)
        assert "java.lang.IllegalStateException: codec not ready" in str(result)

    @pytest.mark.asyncio
    async def test_should_bound_collected_server_output_to_the_latest_lines(self):
        """should bound collected server output to the latest lines."""

        manager = create_manager()
        lines = []
        process = FakeProcess([f"line-{index}" for index in range(110)])

        await manager._collect_server_output(process, lines)

        assert len(lines) == 100
        assert lines[0] == "line-10"
        assert lines[-1] == "line-109"


class TestConsumeFramesLoop:
    @pytest.mark.asyncio
    async def test_should_absorb_a_rejected_cancellation_after_a_stream_read_error(
        self,
    ):
        """should absorb a rejected cancellation after a stream read error."""

        manager = create_manager(options={"idle_timeout_ms": 0})
        stream_error = RuntimeError(
            "The underlying readable ended before the struct was deserialized"
        )
        reader = RaisingReader(stream_error)
        writer = FakeWriter()
        writer.close_error = stream_error
        manager._stream_reader_epoch = 0
        manager._reader = reader
        manager._writer = writer
        manager._initialized = True

        assert await manager._consume_frames_loop(reader) is None

        assert writer.close_calls == 1
        assert manager.is_connected() is False

    @pytest.mark.asyncio
    async def test_should_disconnect_the_current_session_after_a_clean_stream_end(self):
        """should disconnect the current session after a clean stream end."""

        manager = create_manager(options={"idle_timeout_ms": 0})
        reader = RaisingReader(asyncio.IncompleteReadError(b"", 12))
        writer = FakeWriter()
        manager._reader = reader
        manager._writer = writer
        manager._initialized = True

        await manager._consume_frames_loop(reader)

        assert writer.close_calls == 1
        assert manager.is_connected() is False

    @pytest.mark.asyncio
    async def test_should_not_disconnect_a_replacement_session_when_an_obsolete_reader_ends(
        self,
    ):
        """should not disconnect a replacement session when an obsolete reader ends."""

        manager = create_manager(options={"idle_timeout_ms": 0})
        obsolete_reader = RaisingReader(asyncio.IncompleteReadError(b"", 12))
        replacement_reader = object()
        writer = FakeWriter()
        manager._reader = replacement_reader
        manager._writer = writer
        manager._initialized = True

        await manager._consume_frames_loop(obsolete_reader)

        assert writer.close_calls == 0
        assert manager.is_connected() is True


class TestDeviceClockFrameFreshness:
    def test_parses_android_uptime_from_every_timeutils_format(self):
        """parses Android uptime from every TimeUtils format."""

        assert (
            parse_device_uptime_ms("  mLastWakeTime=324781136 (228676 ms ago)\n")
            == 325009812
        )
        assert parse_device_uptime_ms("mLastWakeTime=1000 (in 200 ms)") == 800
        assert parse_device_uptime_ms("mLastWakeTime=1000 (now)") == 1000
        with pytest.raises(ValueError, match="Unable to read Android device uptime"):
            parse_device_uptime_ms("no uptime here")

    @pytest.mark.asyncio
    async def test_samples_the_device_uptime_and_brackets_it_with_host_clocks(self):
        """samples the device uptime and brackets it with host clocks."""

        adb = ClockAdb()
        manager = create_manager(adb=adb)
        manager._monotonic_time_us = Mock(side_effect=[10_000_000, 10_020_000])
        with mock.patch.object(sm.time, "time", side_effect=[2.0, 2.020]):
            result = await manager._read_device_clock_calibration()

        assert adb.shell_calls == [["dumpsys", "power"]]
        assert result.device_uptime_us == 1_050_000
        assert result.host_monotonic_us == 10_010_000
        assert result.host_wall_time_ms == 2_010
        assert result.round_trip_us == 20_000

    @pytest.mark.asyncio
    async def test_drops_frames_captured_before_the_device_clock_barrier(self):
        """drops frames captured before the device-clock barrier."""

        manager = create_manager(options={"idle_timeout_ms": 0})
        listener = Mock()
        manager.subscribe_keyframes(listener)
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_000_000
        warn = mock.patch.object(sm.logger, "warning")

        with warn as warn_mock:
            barrier = await manager.set_freshness_barrier("completed input action")
            assert barrier == 1_006_000

            manager._process_packet(SPS_PACKET, None)
            manager._process_packet(idr_frame(0x01), 1_005_999)
            assert manager.get_latest_raw_keyframe() is None
            listener.assert_not_called()
            assert "completed input action" in str(manager._frame_freshness_error)
            assert not any(
                "predates the completed input action" in str(call.args[0])
                for call in warn_mock.call_args_list
            )

            manager._process_packet(idr_frame(0x02), 1_006_000)
            assert manager.get_latest_raw_keyframe().data[5] == 0x02
            assert listener.call_count == 1
            assert manager._frame_freshness_error is None

    def test_ignores_packets_delivered_by_an_obsolete_stream_reader(self):
        """ignores packets delivered by an obsolete stream reader."""

        manager = create_manager()
        manager._stream_reader_epoch = 2

        manager._process_packet(SPS_PACKET, None, 1)
        manager._process_packet(idr_frame(0x01), 1_000_000, 1)

        assert manager._sps_header is None
        assert manager._last_raw_keyframe is None

    @pytest.mark.asyncio
    async def test_projects_every_barrier_from_one_stream_epoch_clock_sample(self):
        """projects every barrier from one stream-epoch clock sample."""

        manager = create_manager()
        read_clock = AsyncMock(return_value=calibration())
        with mock.patch.object(
            manager, "_read_device_clock_calibration", new=read_clock
        ):
            await manager.ensure_frame_clock_calibration()

        manager._monotonic_time_us = Mock(side_effect=[10_100_000, 10_250_000])
        assert (
            await manager.set_freshness_barrier("completed input action") == 1_106_000
        )
        assert await manager.set_freshness_barrier("stale planning frame") == 1_256_000

        read_clock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_projects_a_deferred_action_barrier_from_when_the_action_completed(
        self,
    ):
        """projects a deferred action barrier from when the action completed."""

        manager = create_manager()
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_500_000

        barrier = await manager.set_freshness_barrier(
            "completed input action while scrcpy was unavailable",
            {"host_monotonic_us": 10_100_000},
        )

        assert barrier == 1_106_000

        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(idr_frame(0x01), 1_200_000)
        assert manager.get_latest_raw_keyframe().data[5] == 0x01

    @pytest.mark.asyncio
    async def test_preserves_a_cached_frame_that_already_crosses_a_completed_action_barrier(
        self,
    ):
        """preserves a cached frame that already crosses a completed-action barrier."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"post-action-frame"
        manager._last_raw_keyframe_pts_us = 1_200_000
        manager._last_raw_keyframe_at = 2_000
        manager._device_clock_calibration = calibration()

        await manager.set_freshness_barrier(
            "completed input action", {"host_monotonic_us": 10_100_000}
        )

        assert manager._last_raw_keyframe == b"post-action-frame"
        assert manager._last_raw_keyframe_pts_us == 1_200_000

    @pytest.mark.asyncio
    async def test_rejects_a_delayed_first_frame_even_while_the_new_stream_startup_window_is_active(
        self,
    ):
        """rejects a delayed first frame even while the new-stream startup window is active."""

        reset_video = AsyncMock()
        manager = create_manager()
        manager._controller = SimpleNamespace(reset_video=reset_video)
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"delayed-in-transport"
        manager._last_raw_keyframe_pts_us = 1_000_000
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}
        manager._device_clock_calibration = calibration(device_uptime_us=5_000_000)
        manager._monotonic_time_us = lambda: 10_000_000
        manager.ensure_connected = AsyncMock()
        manager._reset_idle_timer = Mock()
        wait_for_next = AsyncMock(
            side_effect=RuntimeError("no fresh frame after delayed baseline")
        )
        disconnect = AsyncMock()
        decode = AsyncMock()

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            spy_async(manager, "set_freshness_barrier") as set_barrier,
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            with pytest.raises(ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert error.value.failure_kind == "freshness-target"
        assert error.value.timeout_ms == 300
        wait_for_next.assert_awaited_once()
        set_barrier.assert_awaited_once_with("stale planning frame")
        reset_video.assert_not_awaited()
        disconnect.assert_awaited_once()
        decode.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_the_startup_timeout_while_waiting_for_the_first_data_frame_of_a_new_stream(
        self,
    ):
        """uses the startup timeout while waiting for the first data frame of a new stream."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}
        manager._device_clock_calibration = calibration(device_uptime_us=2_000_000)
        manager._monotonic_time_us = lambda: 10_000_000
        manager.ensure_connected = AsyncMock()
        manager._reset_idle_timer = Mock()
        wait_for_next = AsyncMock(
            return_value=RawKeyframe(
                data=b"initial-frame",
                header=b"header",
                pts_us=2_000_000,
                estimated_age_ms=0,
                stream_epoch=manager._stream_epoch,
                captured_at=2_000,
            )
        )
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        startup_wait_ms = wait_for_next.await_args.args[0]
        assert startup_wait_ms > 4_000
        assert startup_wait_ms <= 5_000
        assert manager._stream_startup_window is None

    @pytest.mark.asyncio
    async def test_deduplicates_concurrent_clock_calibration_for_one_stream_epoch(self):
        """deduplicates concurrent clock calibration for one stream epoch."""

        manager = create_manager()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        calls = []

        def read_clock():
            calls.append(1)
            return future

        manager._read_device_clock_calibration = read_clock
        first = asyncio.ensure_future(manager.ensure_frame_clock_calibration())
        second = asyncio.ensure_future(manager.ensure_frame_clock_calibration())
        await asyncio.sleep(0)
        future.set_result(calibration())

        assert await asyncio.gather(first, second) == [None, None]
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_discards_an_in_flight_clock_sample_from_a_disconnected_epoch(self):
        """discards an in-flight clock sample from a disconnected epoch."""

        manager = create_manager()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        manager._read_device_clock_calibration = lambda: future

        calibration_task = asyncio.ensure_future(
            manager.ensure_frame_clock_calibration()
        )
        await asyncio.sleep(0)
        await manager.disconnect()
        future.set_result(calibration())

        with pytest.raises(RuntimeError, match="stream epoch changed"):
            await calibration_task
        assert manager._device_clock_calibration is None

    @pytest.mark.asyncio
    async def test_requires_a_stream_epoch_clock_anchor_before_arming_a_barrier(self):
        """requires a stream-epoch clock anchor before arming a barrier."""

        manager = create_manager()
        read_clock = Mock()
        manager._read_device_clock_calibration = read_clock

        with pytest.raises(
            RuntimeError, match="not calibrated for the current stream epoch"
        ):
            await manager.set_freshness_barrier("completed input action")

        read_clock.assert_not_called()

    @pytest.mark.asyncio
    async def test_takes_a_new_clock_sample_after_the_stream_epoch_is_reset(self):
        """takes a new clock sample after the stream epoch is reset."""

        manager = create_manager()
        read_clock = AsyncMock(
            side_effect=[
                calibration(),
                calibration(
                    device_uptime_us=2_000_000,
                    host_monotonic_us=20_000_000,
                    host_wall_time_ms=3_000,
                    round_trip_us=12_000,
                ),
            ]
        )
        with mock.patch.object(
            manager, "_read_device_clock_calibration", new=read_clock
        ):
            await manager.ensure_frame_clock_calibration()
            await manager.disconnect()
            await manager.ensure_frame_clock_calibration()

        assert read_clock.await_count == 2
        assert manager._device_clock_calibration.device_uptime_us == 2_000_000

    def test_derives_host_capture_time_and_absolute_age_from_calibrated_pts(self):
        """derives host capture time and absolute age from calibrated PTS."""

        manager = create_manager()
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_100_000

        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(idr_frame(0x01), 1_050_000)

        frame = manager.get_latest_raw_keyframe()
        assert frame.captured_at == 2050
        assert frame.estimated_age_ms == 50
        assert frame.pts_us == 1_050_000

    def test_does_not_use_android_or_host_wall_clock_time_for_frame_age(self):
        """does not use Android or host wall-clock time for frame age."""

        manager = create_manager()
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_100_000

        with mock.patch.object(sm.time, "time", return_value=9_999_999_999.999):
            assert manager._estimate_frame_age_us(1_050_000) == 50_000

    def test_includes_half_the_clock_calibration_rtt_in_the_frame_age_upper_bound(self):
        """includes half the clock-calibration RTT in the frame-age upper bound."""

        manager = create_manager()
        manager._device_clock_calibration = calibration(round_trip_us=5_000_000)
        manager._monotonic_time_us = lambda: 10_000_000

        estimate = manager._estimate_frame_age(1_000_000)
        assert estimate.estimated_age_us == 0
        assert estimate.calibration_uncertainty_us == 2_500_000
        assert estimate.upper_bound_us == 2_500_000
        assert manager._is_frame_age_acceptable(1_000_000) is False

    def test_accepts_a_frame_only_when_estimated_age_plus_uncertainty_is_within_500ms(
        self,
    ):
        """accepts a frame only when estimated age plus uncertainty is within 500ms."""

        manager = create_manager()
        manager._device_clock_calibration = calibration(
            device_uptime_us=1_490_000, round_trip_us=20_000
        )
        manager._monotonic_time_us = lambda: 10_000_000

        assert manager._is_frame_age_acceptable(1_000_000) is True

        manager._device_clock_calibration.round_trip_us = 22_000
        assert manager._is_frame_age_acceptable(1_000_000) is False

    @pytest.mark.asyncio
    async def test_recalibrates_instead_of_resetting_when_only_clock_uncertainty_makes_a_planning_frame_look_stale(
        self,
    ):
        """recalibrates instead of resetting when only clock uncertainty makes a planning frame look stale."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_cached_planning_frame(manager, reset_video=reset_video)
        read_clock = AsyncMock(
            return_value=calibration(device_uptime_us=2_000_000, round_trip_us=20_000)
        )
        disconnect = AsyncMock()
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(
                manager, "_read_device_clock_calibration", new=read_clock
            ),
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        assert read_clock.await_count == 1
        assert manager._device_clock_calibration.round_trip_us == 20_000
        barrier.assert_not_awaited()
        reset_video.assert_not_awaited()
        disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_a_persistently_uncertain_clock_only_once_per_calibration_lifetime(
        self,
    ):
        """retries a persistently uncertain clock only once per calibration lifetime."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_cached_planning_frame(manager, reset_video=reset_video)
        read_clock = AsyncMock(
            return_value=calibration(
                device_uptime_us=2_000_000, round_trip_us=1_600_000
            )
        )
        disconnect = AsyncMock()
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(
                manager, "_read_device_clock_calibration", new=read_clock
            ),
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        assert read_clock.await_count == 1
        assert manager._device_clock_calibration.round_trip_us == 1_544_554
        barrier.assert_not_awaited()
        reset_video.assert_not_awaited()
        disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_estimated_age_when_the_best_effort_recalibration_fails_without_changing_epochs(
        self,
    ):
        """uses estimated age when the best-effort recalibration fails without changing epochs."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_cached_planning_frame(manager, reset_video=reset_video)
        read_clock = AsyncMock(side_effect=RuntimeError("ADB clock sample failed"))
        disconnect = AsyncMock()
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(
                manager, "_read_device_clock_calibration", new=read_clock
            ),
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        read_clock.assert_awaited_once()
        barrier.assert_not_awaited()
        reset_video.assert_not_awaited()
        disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_still_rejects_a_genuinely_stale_planning_frame_when_clock_uncertainty_is_high(
        self,
    ):
        """still rejects a genuinely stale planning frame when clock uncertainty is high."""

        manager = create_manager()
        prepare_cached_planning_frame(
            manager, pts_us=1_400_000, frame_data=b"stale-frame"
        )
        read_clock = Mock()
        manager._read_device_clock_calibration = read_clock
        wait_for_next = AsyncMock(side_effect=RuntimeError("no fresh frame"))
        disconnect = AsyncMock()

        with (
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
        ):
            with pytest.raises(ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert error.value.failure_kind == "freshness-target"
        read_clock.assert_not_called()
        barrier.assert_awaited_once_with("stale planning frame")
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_includes_the_recalibration_wait_when_an_uncertainty_only_planning_frame_is_rechecked(
        self,
    ):
        """includes the recalibration wait when an uncertainty-only planning frame is rechecked."""

        manager = create_manager()
        prepare_cached_planning_frame(manager, pts_us=2_000_000, round_trip_us=599_999)
        manager._device_clock_calibration.device_uptime_us = 2_300_000

        host_monotonic_us = [10_000_000]
        manager._monotonic_time_us = lambda: host_monotonic_us[0]

        async def read_clock():
            host_monotonic_us[0] += 2_200_000
            return calibration(
                device_uptime_us=4_500_000,
                host_monotonic_us=host_monotonic_us[0],
                host_wall_time_ms=4_200,
                round_trip_us=800_000,
            )

        manager._read_device_clock_calibration = read_clock
        original_estimate = manager._estimate_frame_age
        candidate = manager._get_cached_keyframe_candidate()

        with mock.patch.object(
            manager, "_estimate_frame_age", wraps=original_estimate
        ) as estimate:
            assert await manager._is_planning_candidate_fresh_enough(candidate) is False

        hosts = [call.args[1] for call in estimate.call_args_list]
        assert hosts == [10_000_000, 12_200_000]
        assert manager._device_clock_calibration.device_uptime_us == 2_300_000
        assert manager._device_clock_calibration.host_monotonic_us == 10_000_000
        assert manager._device_clock_calibration.round_trip_us == 599_999
        assert (
            original_estimate(candidate.pts_us, 12_200_000).estimated_age_us
            == 2_500_000
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["improved", "failed"])
    async def test_rejects_a_frame_that_expires_while_clock_recalibration_is(
        self, outcome
    ):
        """rejects a frame that expires while clock recalibration is %s."""

        manager = create_manager()
        prepare_cached_planning_frame(manager, pts_us=1_700_000, round_trip_us=600_000)

        async def read_clock():
            await asyncio.sleep(0)
            manager._monotonic_time_us = lambda: 12_200_000
            if outcome == "failed":
                raise RuntimeError("clock sample failed")
            return calibration(
                device_uptime_us=4_200_000,
                host_monotonic_us=12_200_000,
                host_wall_time_ms=4_200,
                round_trip_us=20_000,
            )

        manager._read_device_clock_calibration = read_clock

        assert (
            await manager._is_planning_candidate_fresh_enough(
                manager._get_cached_keyframe_candidate()
            )
            is False
        )
        expected = 20_000 if outcome == "improved" else 600_000
        assert manager._device_clock_calibration.round_trip_us == expected

    @pytest.mark.asyncio
    async def test_throws_the_uncalibrated_clock_error_when_recalibration_clears_the_anchor(
        self,
    ):
        """throws the uncalibrated-clock error when recalibration clears the anchor."""

        manager = create_manager()
        prepare_cached_planning_frame(manager, pts_us=2_000_000, round_trip_us=599_999)
        manager._device_clock_calibration.device_uptime_us = 2_300_000

        host_monotonic_us = [10_000_000]
        manager._monotonic_time_us = lambda: host_monotonic_us[0]

        async def read_clock():
            host_monotonic_us[0] += 2_200_000
            manager._device_clock_calibration = None
            raise RuntimeError("calibration invalidated")

        manager._read_device_clock_calibration = read_clock
        candidate = manager._get_cached_keyframe_candidate()

        with pytest.raises(
            RuntimeError,
            match=(
                "Scrcpy frame clock is not calibrated; cannot prove planning freshness"
            ),
        ):
            await manager._is_planning_candidate_fresh_enough(candidate)
        assert manager._device_clock_calibration is None
        assert candidate.stream_epoch is manager._stream_epoch

    @pytest.mark.asyncio
    async def test_rejects_an_uncertainty_only_candidate_when_its_stream_epoch_changes_during_recalibration(
        self,
    ):
        """rejects an uncertainty-only candidate when its stream epoch changes during recalibration."""

        manager = create_manager()
        prepare_cached_planning_frame(manager, frame_data=b"obsolete-frame")

        async def read_clock():
            manager._advance_stream_epoch()
            manager._device_clock_calibration = None
            raise RuntimeError("calibration invalidated")

        manager._read_device_clock_calibration = read_clock
        disconnect = AsyncMock()
        decode = AsyncMock()

        with (
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            with pytest.raises(ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert "stream epoch changed while recalibrating" in str(error.value)
        decode.assert_not_awaited()
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recalibrates_the_clock_anchor_when_frame_pts_moves_backwards(self):
        """recalibrates the clock anchor when frame PTS moves backwards."""

        manager = create_manager()
        manager._device_clock_calibration = calibration(device_uptime_us=1_100_000)
        manager._monotonic_time_us = lambda: 10_000_000

        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(idr_frame(0x01), 1_050_000)
        assert manager.get_latest_raw_keyframe().data[5] == 0x01

        manager._process_packet(idr_frame(0x02), 1_040_000)
        assert manager.get_latest_raw_keyframe() is None
        assert manager._frame_freshness_barrier_pending is True
        assert manager._frame_freshness_barrier_pts_us is None
        assert manager._device_clock_calibration is None
        assert "PTS moved backwards" in str(manager._frame_freshness_error)

        manager._process_packet(idr_frame(0x03), 1_200_000)
        assert manager.get_latest_raw_keyframe() is None

        read_clock = AsyncMock(
            return_value=calibration(
                device_uptime_us=200_000,
                host_monotonic_us=10_000_000,
                host_wall_time_ms=2_100,
                round_trip_us=10_000,
            )
        )
        with mock.patch.object(
            manager, "_read_device_clock_calibration", new=read_clock
        ):
            await manager.ensure_frame_clock_calibration()
        manager._process_packet(idr_frame(0x04), 200_000)

        read_clock.assert_awaited_once()
        assert manager._frame_freshness_barrier_pending is False
        assert manager.get_latest_raw_keyframe().data[5] == 0x04

    @pytest.mark.asyncio
    async def test_hides_over_age_frames_from_continuous_frame_consumers(self):
        """hides over-age frames from continuous frame consumers."""

        manager = create_manager(options={"idle_timeout_ms": 0})
        listener = Mock()
        manager.subscribe_keyframes(listener)
        manager._device_clock_calibration = calibration(device_uptime_us=2_000_000)
        manager._monotonic_time_us = lambda: 10_000_000

        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(idr_frame(0x01), 1_000_000)
        assert manager.get_latest_raw_keyframe() is None
        listener.assert_not_called()

        manager._process_packet(idr_frame(0x02), 1_800_000)
        assert manager.get_latest_raw_keyframe().data[5] == 0x02
        assert listener.call_count == 1

    @pytest.mark.asyncio
    async def test_reuses_a_cached_frame_that_crossed_the_active_action_barrier(self):
        """reuses a cached frame that crossed the active action barrier."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"post-action"
        manager._last_raw_keyframe_pts_us = 1_050_000
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_100_000
        manager.ensure_connected = AsyncMock()
        manager._reset_idle_timer = Mock()
        wait_for_next = AsyncMock()
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        barrier.assert_not_awaited()
        wait_for_next.assert_not_awaited()
        decode.assert_awaited_once_with(b"header" + b"post-action")

    @pytest.mark.asyncio
    async def test_adds_a_planning_barrier_for_a_post_action_frame_that_is_already_over_age(
        self,
    ):
        """adds a planning barrier for a post-action frame that is already over-age."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"post-action-backlog"
        manager._last_raw_keyframe_pts_us = 1_100_000
        manager._frame_freshness_barrier_pts_us = 1_000_000
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}
        manager._device_clock_calibration = calibration(device_uptime_us=2_000_000)
        manager._monotonic_time_us = lambda: 10_000_000
        manager.ensure_connected = AsyncMock()
        manager._reset_idle_timer = Mock()
        wait_for_next = AsyncMock(
            return_value=RawKeyframe(
                data=b"current",
                header=b"header",
                pts_us=2_006_000,
                estimated_age_ms=0,
                stream_epoch=manager._stream_epoch,
                captured_at=2_000,
            )
        )
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        barrier.assert_awaited_once_with("stale planning frame")
        assert manager._frame_freshness_barrier_pts_us == 2_006_000
        decode.assert_awaited_once_with(b"header" + b"current")

    @pytest.mark.asyncio
    async def test_adds_a_planning_barrier_after_the_new_stream_startup_window_expires(
        self,
    ):
        """adds a planning barrier after the new-stream startup window expires."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"first-planning-backlog"
        manager._last_raw_keyframe_pts_us = 1_000_000
        manager._stream_startup_window = {"deadline_at": sm._now_ms() - 1}
        manager._device_clock_calibration = calibration(device_uptime_us=2_000_000)
        manager._monotonic_time_us = lambda: 10_000_000
        manager.ensure_connected = AsyncMock()
        manager._reset_idle_timer = Mock()
        wait_for_next = AsyncMock(
            return_value=RawKeyframe(
                data=b"current",
                header=b"header",
                pts_us=2_006_000,
                estimated_age_ms=0,
                stream_epoch=manager._stream_epoch,
                captured_at=2_000,
            )
        )
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame()

        barrier.assert_awaited_once_with("stale planning frame")

    @pytest.mark.asyncio
    async def test_returns_a_quiet_diagnostic_when_a_static_screen_cannot_cross_the_planning_barrier(
        self,
    ):
        """returns a quiet diagnostic when a static screen cannot cross the Planning barrier."""

        manager = create_manager()
        manager._sps_header = b"old-header"
        manager._last_raw_keyframe = b"stale-static-frame"
        manager._last_raw_keyframe_pts_us = 1_000_000
        manager._device_clock_calibration = calibration(device_uptime_us=2_000_000)
        manager._monotonic_time_us = lambda: 10_000_000
        ensure_connected = AsyncMock()
        manager.ensure_connected = ensure_connected
        disconnect = AsyncMock()
        wait_for_next = AsyncMock(side_effect=RuntimeError("no post-action frame"))
        decode = AsyncMock()

        with (
            mock.patch.object(sm.logger, "warning") as warn,
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            with pytest.raises(ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert error.value.failure_kind == "freshness-target"
        assert error.value.timeout_ms == 300
        assert error.value.video_bit_rate == 100_000_000
        ensure_connected.assert_awaited_once()
        disconnect.assert_awaited_once()
        barrier.assert_awaited_once_with("stale planning frame")
        decode.assert_not_awaited()
        warn.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_capture_state_when_a_current_deferred_keyframe_is_decoded(
        self,
    ):
        """updates capture state when a current deferred keyframe is decoded."""

        manager = create_manager()
        current_stream_epoch = object()
        manager._stream_epoch = current_stream_epoch
        manager._video_resolution = {"width": 1080, "height": 1920}
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}
        decode = AsyncMock(return_value=jpeg_frame(1200, 2608))

        with mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode):
            result = await manager.decode_raw_keyframe_to_jpeg(
                RawKeyframe(
                    data=b"frame",
                    header=b"header",
                    stream_epoch=current_stream_epoch,
                    captured_at=sm._now_ms(),
                )
            )

        assert result == jpeg_frame(1200, 2608)
        assert manager.get_resolution() == {"width": 1200, "height": 2608}
        assert manager._has_established_video_frame is True
        assert manager._stream_startup_window is None

    @pytest.mark.asyncio
    async def test_decodes_an_untagged_keyframe_without_mutating_current_stream_state(
        self,
    ):
        """decodes an untagged keyframe without mutating current stream state."""

        manager = create_manager()
        startup_window = {"deadline_at": sm._now_ms() + 5_000}
        manager._video_resolution = {"width": 1080, "height": 1920}
        manager._stream_startup_window = startup_window
        decode = AsyncMock(return_value=jpeg_frame(1200, 2608))

        with mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode):
            result = await manager.decode_raw_keyframe_to_jpeg(
                RawKeyframe(
                    data=b"compatibility-frame",
                    header=b"header",
                    captured_at=sm._now_ms(),
                )
            )

        assert result == jpeg_frame(1200, 2608)
        assert manager.get_resolution() == {"width": 1080, "height": 1920}
        assert manager._has_established_video_frame is False
        assert manager._stream_startup_window is startup_window

    @pytest.mark.asyncio
    async def test_does_not_let_a_deferred_keyframe_from_a_replaced_manager_overwrite_current_state(
        self,
    ):
        """does not let a deferred keyframe from a replaced manager overwrite current state."""

        old_manager = create_manager()
        manager = create_manager()
        startup_window = {"deadline_at": sm._now_ms() + 5_000}
        old_manager._advance_stream_epoch()
        manager._advance_stream_epoch()
        old_stream_epoch = old_manager._stream_epoch
        assert manager._stream_epoch is not old_stream_epoch
        manager._video_resolution = {"width": 1080, "height": 1920}
        manager._stream_startup_window = startup_window
        decode = AsyncMock(return_value=jpeg_frame(1200, 2608))

        with mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode):
            result = await manager.decode_raw_keyframe_to_jpeg(
                RawKeyframe(
                    data=b"old-frame",
                    header=b"old-header",
                    stream_epoch=old_stream_epoch,
                    captured_at=sm._now_ms(),
                )
            )

        assert result == jpeg_frame(1200, 2608)
        assert manager.get_resolution() == {"width": 1080, "height": 1920}
        assert manager._has_established_video_frame is False
        assert manager._stream_startup_window is startup_window

    @pytest.mark.asyncio
    async def test_rejects_frames_without_pts_instead_of_treating_arrival_time_as_freshness(
        self,
    ):
        """rejects frames without PTS instead of treating arrival time as freshness."""

        manager = create_manager()
        manager._sps_header = b"header"
        manager._last_raw_keyframe = b"no-pts"
        manager._device_clock_calibration = calibration()
        manager.ensure_connected = AsyncMock()
        disconnect = AsyncMock()

        with mock.patch.object(manager, "disconnect", new=disconnect):
            with pytest.raises(RuntimeError, match="has no PTS metadata"):
                await manager.get_screenshot_jpeg()


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_should_reset_all_state(self):
        """should reset all state."""

        manager = create_manager()
        manager._sps_header = b"sps"
        manager._last_raw_keyframe = b"keyframe"
        manager._initialized = True
        manager._keyframe_waiters = [object()]
        manager._reader = object()
        manager._writer = object()
        manager._frame_freshness_barrier_pts_us = 123
        manager._device_clock_calibration = calibration()
        manager._last_frame_pts_us = 456
        manager._frame_freshness_error = RuntimeError("stale")
        manager._has_established_video_frame = True
        manager._video_reset_state = {"frame_accepted": True}
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}

        await manager.disconnect()

        assert manager._sps_header is None
        assert manager._last_raw_keyframe is None
        assert manager._initialized is False
        assert manager._keyframe_waiters == []
        assert manager._reader is None
        assert manager._writer is None
        assert manager._frame_freshness_barrier_pts_us is None
        assert manager._device_clock_calibration is None
        assert manager._last_frame_pts_us is None
        assert manager._frame_freshness_error is None
        assert manager._has_established_video_frame is False
        assert manager._video_reset_state is None
        assert manager._stream_startup_window is None

    @pytest.mark.asyncio
    async def test_should_clear_idle_timer(self):
        """should clear idle timer."""

        manager = create_manager()
        manager._idle_handle = asyncio.get_running_loop().call_later(10, lambda: None)

        await manager.disconnect()

        assert manager._idle_handle is None

    @pytest.mark.asyncio
    async def test_should_handle_scrcpy_client_close_error_gracefully(self):
        """should handle scrcpyClient.close() error gracefully."""

        manager = create_manager()
        writer = FakeWriter()
        writer.close_error = RuntimeError("close failed")
        manager._writer = writer

        assert await manager.disconnect() is None
        assert manager._writer is None

    @pytest.mark.asyncio
    async def test_closes_the_owned_adb_transport_only_when_permanently_disposed(self):
        """closes the owned ADB transport only when permanently disposed."""

        close = AsyncMock()
        adb = SimpleNamespace(close=close)
        manager = create_manager(adb=adb)

        await manager.disconnect()
        close.assert_not_awaited()

        await manager.dispose()
        await manager.dispose()
        close.assert_awaited_once()
        with pytest.raises(RuntimeError, match="Scrcpy manager has been disposed"):
            await manager.ensure_connected()

    @pytest.mark.asyncio
    async def test_shares_one_complete_disposal_across_concurrent_callers(self):
        """shares one complete disposal across concurrent callers."""

        release = asyncio.Event()
        close_calls = []

        async def close():
            close_calls.append(1)
            await release.wait()

        adb = SimpleNamespace(close=close)
        manager = create_manager(adb=adb)

        first_dispose = asyncio.ensure_future(manager.dispose())
        second_dispose = asyncio.ensure_future(manager.dispose())
        await _wait_until(lambda: len(close_calls) == 1)
        assert not second_dispose.done()
        assert len(close_calls) == 1

        release.set()
        assert await asyncio.gather(first_dispose, second_dispose) == [
            None,
            None,
        ]
        assert len(close_calls) == 1

    @pytest.mark.asyncio
    async def test_waits_for_an_in_flight_connection_before_disposing_its_adb_transport(
        self,
    ):
        """waits for an in-flight connection before disposing its ADB transport."""

        close = AsyncMock()
        adb = SimpleNamespace(close=close)
        manager = create_manager(adb=adb)
        loop = asyncio.get_running_loop()
        connection = loop.create_future()

        manager._connect_scrcpy = lambda: connection

        connecting = asyncio.ensure_future(manager.ensure_connected())
        disposing = asyncio.ensure_future(manager.dispose())
        await asyncio.sleep(0)
        close.assert_not_awaited()
        connection.set_result(None)

        assert await asyncio.gather(connecting, disposing) == [None, None]
        close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_should_cancel_stream_reader_to_stop_consume_frames_loop(self):
        """should cancel streamReader to stop consumeFramesLoop.

        Python stops the loop by cancelling its consumer task instead of
        calling StreamReader.cancel().
        """

        manager = create_manager(options={"idle_timeout_ms": 0})
        started = asyncio.Event()

        async def consumer():
            started.set()
            await asyncio.sleep(3600)

        manager._reader = object()
        manager._consumer_task = asyncio.ensure_future(consumer())
        await started.wait()

        await manager.disconnect()

        assert manager._consumer_task is None
        assert manager._reader is None
        assert started.is_set() is True

    @pytest.mark.asyncio
    async def test_should_wait_for_asynchronous_stream_reader_cancellation(self):
        """should wait for asynchronous streamReader cancellation.

        Python's StreamReader has no cancel(); the equivalent is waiting for the
        consumer task to finish its asynchronous cancellation cleanup.
        """

        manager = create_manager(options={"idle_timeout_ms": 0})
        release = asyncio.Event()
        started = asyncio.Event()

        async def consumer():
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await release.wait()

        manager._consumer_task = asyncio.ensure_future(consumer())
        await started.wait()

        disconnect_task = asyncio.ensure_future(manager.disconnect())
        await asyncio.sleep(0)
        assert manager._consumer_task is None
        assert not disconnect_task.done()

        release.set()
        await disconnect_task
        assert disconnect_task.done()

    @pytest.mark.asyncio
    async def test_should_handle_stream_reader_cancel_error_gracefully(self):
        """should handle streamReader.cancel() error gracefully.

        Python surfaces this through the consumer task raising during its
        cancellation cleanup; disconnect() must suppress it.
        """

        manager = create_manager(options={"idle_timeout_ms": 0})
        started = asyncio.Event()

        async def consumer():
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise RuntimeError("stream already errored") from None

        manager._reader = object()
        manager._consumer_task = asyncio.ensure_future(consumer())
        await started.wait()

        assert await manager.disconnect() is None
        assert manager._reader is None

    @pytest.mark.asyncio
    async def test_should_null_references_before_awaiting_close_to_prevent_race_conditions(
        self,
    ):
        """should null references before awaiting close to prevent race conditions."""

        manager = create_manager()
        client_nulled_before_close = []

        class CheckingWriter:
            def close(self):
                client_nulled_before_close.append(manager._writer is None)

            async def wait_closed(self):
                return None

        manager._writer = CheckingWriter()
        manager._reader = object()

        await manager.disconnect()

        assert client_nulled_before_close == [True]
        assert manager._reader is None
