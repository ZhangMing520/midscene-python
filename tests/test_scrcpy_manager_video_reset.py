"""Port of upstream packages/android/tests/unit-test/scrcpy-manager-video-reset.test.ts."""

import asyncio
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, Mock

import pytest

from midscene.android import scrcpy_manager as sm
from midscene.android.scrcpy_manager import (
    DeviceClockCalibration,
    RawKeyframe,
    ScrcpyScreenshotManager,
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


def calibration(host_wall_time_ms=2_000):
    return DeviceClockCalibration(
        device_uptime_us=2_000_000,
        host_monotonic_us=10_000_000,
        host_wall_time_ms=host_wall_time_ms,
        round_trip_us=10_000,
    )


async def _noop_push(local_path, remote_path):
    return None


def create_manager(options=None):
    return ScrcpyScreenshotManager(
        {}, _noop_push, options if options is not None else {}
    )


class FakeWriter:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1

    async def wait_closed(self):
        return None


def prepare_established_stale_manager(
    manager,
    reset_video,
    *,
    host_wall_time_ms=2_000,
    writer=None,
):
    manager._has_established_video_frame = True
    manager._controller = SimpleNamespace(reset_video=reset_video)
    manager._sps_header = b"old-header"
    manager._last_raw_keyframe = b"stale-static-frame"
    manager._last_raw_keyframe_pts_us = 1_000_000
    manager._device_clock_calibration = calibration(host_wall_time_ms)
    manager._monotonic_time_us = lambda: 10_000_000
    manager.ensure_connected = AsyncMock()
    manager._reset_idle_timer = Mock()
    if writer is not None:
        manager._writer = writer


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


class TestVideoReset:
    @pytest.mark.asyncio
    async def test_resets_an_established_static_video_stream_before_closing_the_connection(
        self,
    ):
        """resets an established static video stream before closing the connection."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        wait_calls = []

        async def wait_for_next(timeout_ms):
            wait_calls.append(timeout_ms)
            if len(wait_calls) == 1:
                raise RuntimeError("no natural frame within 10ms")
            return RawKeyframe(
                data=b"post-reset-frame",
                header=b"new-header",
                pts_us=2_006_000,
                estimated_age_ms=0,
                stream_epoch=manager._stream_epoch,
                captured_at=2_000,
            )

        wait_for_next = AsyncMock(side_effect=wait_for_next)
        disconnect = AsyncMock()
        decode = AsyncMock(return_value=jpeg_frame(1200, 2608))
        epoch_before_reset = manager._stream_epoch

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            spy_async(manager, "set_freshness_barrier") as barrier,
            mock.patch.object(manager, "disconnect", new=disconnect),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            assert await manager.get_screenshot_jpeg() == jpeg_frame(1200, 2608)

        assert wait_calls[0] == 10
        reset_video.assert_awaited_once()
        assert manager._stream_epoch is not epoch_before_reset
        barrier.assert_awaited_once_with("stale planning frame")
        disconnect.assert_not_awaited()
        assert manager.get_resolution() == {"width": 1200, "height": 2608}

    @pytest.mark.asyncio
    async def test_uses_a_natural_fresh_frame_without_resetting_video_when_it_arrives_within_10ms(
        self,
    ):
        """uses a natural fresh frame without resetting video when it arrives within 10ms."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        manager._sps_header = b"header"
        wait_for_next = AsyncMock(
            return_value=RawKeyframe(
                data=b"natural-frame",
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

        wait_for_next.assert_awaited_once_with(10)
        reset_video.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_a_post_reset_frame_that_arrives_before_the_control_write_settles(
        self,
    ):
        """uses a post-reset frame that arrives before the control write settles."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        wait_for_next = AsyncMock(
            side_effect=RuntimeError("no natural frame within 10ms")
        )
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            capture = asyncio.ensure_future(manager.get_screenshot_jpeg())
            await _wait_until(lambda: len(reset_calls) == 1)
            manager._process_packet(SPS_PACKET, None)
            manager._process_packet(idr_frame(0x01), 2_006_000)
            reset_future.set_result(None)

            assert await capture == jpeg_frame()

        wait_for_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_waits_up_to_800ms_after_a_successful_reset_control_write_by_default(
        self,
    ):
        """waits up to 800ms after a successful reset control write by default."""

        reset_started = asyncio.Event()
        release_reset = asyncio.Event()

        async def reset_video():
            reset_started.set()
            await release_reset.wait()

        writer = FakeWriter()
        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video, writer=writer)
        wait_calls = []

        async def wait_for_next(timeout_ms):
            wait_calls.append(timeout_ms)
            if len(wait_calls) == 1:
                raise RuntimeError("no natural frame within 10ms")
            return RawKeyframe(
                data=b"delayed-post-reset-frame",
                header=b"new-header",
                pts_us=2_006_000,
                estimated_age_ms=0,
                stream_epoch=manager._stream_epoch,
                captured_at=2_000,
            )

        wait_for_next = AsyncMock(side_effect=wait_for_next)
        decode = AsyncMock(return_value=jpeg_frame())

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "_decode_h264_to_jpeg", new=decode),
        ):
            capture = asyncio.ensure_future(manager.get_screenshot_jpeg())
            await _wait_until(lambda: len(wait_calls) == 1 and reset_started.is_set())
            assert writer.close_calls == 0

            release_reset.set()
            assert await capture == jpeg_frame()

        assert 790 < wait_calls[1] <= 800
        assert writer.close_calls == 0

    @pytest.mark.asyncio
    async def test_shares_one_video_reset_across_concurrent_recovery_callers(self):
        """shares one video reset across concurrent recovery callers."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        manager = create_manager()
        manager._controller = SimpleNamespace(reset_video=reset_video)
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_000_000

        first = asyncio.ensure_future(manager._request_video_reset())
        await _wait_until(lambda: len(reset_calls) == 1)
        second = asyncio.ensure_future(manager._request_video_reset())
        await asyncio.sleep(0)
        reset_future.set_result(None)

        first_reset, second_reset = await asyncio.gather(first, second)

        assert second_reset is first_reset
        assert len(reset_calls) == 1

    @pytest.mark.asyncio
    async def test_keeps_reset_singleflight_ownership_until_both_the_write_and_a_new_frame_complete(
        self,
    ):
        """keeps reset singleflight ownership until both the write and a new frame complete."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        manager = create_manager()
        manager._controller = SimpleNamespace(reset_video=reset_video)
        manager._device_clock_calibration = calibration()
        manager._monotonic_time_us = lambda: 10_000_000

        first = asyncio.ensure_future(manager._request_video_reset())
        await _wait_until(lambda: len(reset_calls) == 1)
        manager._process_packet(SPS_PACKET, None)
        manager._process_packet(idr_frame(0x01), 2_000_000)
        assert manager._video_reset_state["frame_accepted"] is True

        second = asyncio.ensure_future(manager._request_video_reset())
        await asyncio.sleep(0)
        assert len(reset_calls) == 1
        reset_future.set_result(None)

        first_reset, second_reset = await asyncio.gather(first, second)

        assert second_reset is first_reset
        assert len(reset_calls) == 1
        assert manager._video_reset_state is None

    @pytest.mark.asyncio
    async def test_restores_the_prior_sps_header_when_the_reset_control_write_fails(
        self,
    ):
        """restores the prior SPS header when the reset control write fails."""

        old_header = b"old-header"

        async def reset_video():
            raise RuntimeError("control stream write failed")

        manager = create_manager()
        manager._sps_header = old_header
        manager._controller = SimpleNamespace(reset_video=reset_video)

        with pytest.raises(RuntimeError, match="control stream write failed"):
            await manager._request_video_reset()

        assert manager._sps_header == old_header
        assert manager._video_reset_state is None

    @pytest.mark.asyncio
    async def test_bounds_a_blocked_reset_write_by_the_original_300ms_capture_deadline(
        self,
    ):
        """bounds a blocked reset write by the original 300ms capture deadline."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        writer = FakeWriter()
        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video, writer=writer)

        with pytest.raises(sm.ScrcpyFreshFrameUnavailableError) as error:
            await manager.get_screenshot_jpeg()

        assert error.value.timeout_ms == 300
        assert len(reset_calls) == 1
        assert writer.close_calls == 1
        assert manager._video_reset_state is None
        reset_future.cancel()

    @pytest.mark.asyncio
    async def test_falls_back_to_closing_the_stream_when_video_reset_cannot_produce_a_frame(
        self,
    ):
        """falls back to closing the stream when video reset cannot produce a frame."""

        reset_calls = []

        async def reset_video():
            reset_calls.append(1)
            raise RuntimeError("control stream write failed")

        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        wait_for_next = AsyncMock(
            side_effect=[
                RuntimeError("no natural frame within 10ms"),
                RuntimeError("no frame after reset attempt"),
            ]
        )
        disconnect = AsyncMock()

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
        ):
            with pytest.raises(sm.ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert error.value.failure_kind == "freshness-target"
        assert len(reset_calls) == 1
        assert disconnect.await_count == 1

    @pytest.mark.asyncio
    async def test_reports_when_a_successful_reset_produces_no_data_frames_within_800ms(
        self,
    ):
        """reports when a successful reset produces no data frames within 800ms."""

        reset_video = AsyncMock()
        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        wait_for_next = AsyncMock(side_effect=RuntimeError("no frame"))
        disconnect = AsyncMock()

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
        ):
            with pytest.raises(sm.ScrcpyFreshFrameUnavailableError) as error:
                await manager.get_screenshot_jpeg()

        assert error.value.timeout_ms == 800
        assert "no data packets were observed while reset recovery was active" in str(
            error.value
        )
        reset_video.assert_awaited_once()
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("arrival", ["before", "after"])
    async def test_retains_packet_diagnostics_when_a_rejected_keyframe_arrives_before_or_after_reset_write_completion(
        self, arrival
    ):
        """retains packet diagnostics when a rejected keyframe arrives %s reset write completion."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        manager = create_manager()
        prepare_established_stale_manager(manager, reset_video)
        disconnect = AsyncMock()
        second_wait_entered = asyncio.Event()
        resume = asyncio.Event()
        wait_calls = []

        async def wait_for_next(timeout_ms):
            wait_calls.append(timeout_ms)
            if len(wait_calls) == 1:
                raise RuntimeError("no natural frame within 10ms")
            second_wait_entered.set()
            await resume.wait()
            raise RuntimeError("no frame after reset attempt")

        wait_for_next = AsyncMock(side_effect=wait_for_next)

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
        ):
            capture = asyncio.ensure_future(manager.get_screenshot_jpeg())
            await _wait_until(lambda: len(wait_calls) == 1 and len(reset_calls) == 1)

            if arrival == "after":
                reset_future.set_result(None)
                await _wait_until(second_wait_entered.is_set)

            manager._monotonic_time_us = lambda: 11_000_000
            manager._process_packet(SPS_PACKET, None)
            manager._process_packet(idr_frame(0x01), 2_006_000)

            if arrival == "before":
                reset_future.set_result(None)
                await _wait_until(second_wait_entered.is_set)

            await asyncio.sleep(0)
            assert manager._video_reset_state is None

            resume.set()
            with pytest.raises(sm.ScrcpyFreshFrameUnavailableError) as error:
                await capture

        assert error.value.timeout_ms == 800
        assert "1 data packet was observed while reset recovery was active" in str(
            error.value
        )

    @pytest.mark.asyncio
    async def test_reports_unusable_data_packets_observed_while_reset_recovery_is_active(
        self,
    ):
        """reports unusable data packets observed while reset recovery is active."""

        reset_video = AsyncMock()
        manager = create_manager({"videoResetFrameTimeoutMs": 950})
        prepare_established_stale_manager(manager, reset_video)
        disconnect = AsyncMock()
        second_wait_entered = asyncio.Event()
        resume = asyncio.Event()
        wait_calls = []

        async def wait_for_next(timeout_ms):
            wait_calls.append(timeout_ms)
            if len(wait_calls) == 1:
                raise RuntimeError("no natural frame within 10ms")
            second_wait_entered.set()
            await resume.wait()
            raise RuntimeError("no frame after reset attempt")

        wait_for_next = AsyncMock(side_effect=wait_for_next)

        with (
            mock.patch.object(manager, "_wait_for_next_keyframe", new=wait_for_next),
            mock.patch.object(manager, "disconnect", new=disconnect),
        ):
            capture = asyncio.ensure_future(manager.get_screenshot_jpeg())
            await _wait_until(second_wait_entered.is_set)

            manager._process_packet(SPS_PACKET, None)
            manager._process_packet(idr_frame(0x01), 2_005_000)

            resume.set()
            with pytest.raises(sm.ScrcpyFreshFrameUnavailableError) as error:
                await capture

        assert error.value.timeout_ms == 950
        assert "1 data packet was observed while reset recovery was active" in str(
            error.value
        )
        reset_video.assert_awaited_once()
        disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_observes_a_reset_rejection_that_arrives_after_the_caller_deadline(
        self,
    ):
        """observes a reset rejection that arrives after the caller deadline."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()

        def reset_video():
            return reset_future

        manager = create_manager()
        old_header = b"old-header"
        manager._sps_header = old_header
        manager._controller = SimpleNamespace(reset_video=reset_video)

        with pytest.raises(RuntimeError, match="exceeded the freshness deadline"):
            await manager._request_video_reset(sm._now_ms() + 50)

        reset_future.set_exception(RuntimeError("late control stream rejection"))
        await asyncio.sleep(0.01)

        assert manager._sps_header == old_header
        assert manager._video_reset_state is None

    @pytest.mark.asyncio
    async def test_does_not_wait_for_a_blocked_reset_video_control_write(self):
        """does not wait for a blocked RESET_VIDEO control write."""

        loop = asyncio.get_running_loop()
        reset_future = loop.create_future()
        reset_calls = []

        def reset_video():
            reset_calls.append(1)
            return reset_future

        writer = FakeWriter()
        manager = create_manager()
        manager._has_established_video_frame = True
        manager._stream_startup_window = {"deadline_at": sm._now_ms() + 5_000}
        manager._controller = SimpleNamespace(reset_video=reset_video)
        manager._writer = writer

        reset_request = asyncio.ensure_future(manager._request_video_reset())
        await _wait_until(lambda: len(reset_calls) == 1)
        assert len(reset_calls) == 1

        assert await manager.disconnect() is None
        assert writer.close_calls == 1
        assert manager._video_reset_state is None
        assert manager._has_established_video_frame is False
        assert manager._stream_startup_window is None

        with pytest.raises(RuntimeError, match="exceeded the freshness deadline"):
            await reset_request
        reset_future.cancel()
