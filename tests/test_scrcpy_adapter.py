"""Port of upstream packages/android/tests/unit-test/scrcpy-adapter.test.ts."""

import asyncio
import base64
import inspect

import pytest

from midscene.android.scrcpy_device_adapter import (
    ScrcpyDeviceAdapter,
    format_scrcpy_fresh_frame_failure,
)
from midscene.android.scrcpy_manager import (
    DEFAULT_SCRCPY_CONFIG,
    SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE,
    AdbCommandBackend,
    ScrcpyFreshFrameUnavailableError,
)

DEVICE_INFO = {
    "physical_width": 1080,
    "physical_height": 1920,
    "dpr": 2.625,
    "orientation": 0,
}


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


def jpeg_data_url(buffer: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")


class FakeBackend:
    def __init__(self) -> None:
        self.push_calls = []
        self.close_calls = 0

    async def push(self, local_path, remote_path):
        self.push_calls.append((local_path, remote_path))

    async def screencap_png(self):
        return b"\x89PNG\r\n\x1a\nadb"

    async def close(self):
        self.close_calls += 1


class FakeManager:
    def __init__(self, resolution=None, connected=False):
        self.connected = connected
        self.resolution = resolution and dict(resolution)
        self.validate_calls = 0
        self.validate_error = None
        self.ensure_connected_calls = 0
        self.ensure_connected_errors = []
        self.calibration_calls = 0
        self.barriers = []
        self.barrier_error = None
        self.subscribe_calls = []
        self.unsubscribe_calls = 0
        self.dispose_calls = 0
        self.dispose_error = None
        self.screenshot_calls = 0
        self.screenshot_results = []
        self.is_connected_results = []
        self.events = []

    async def validate_environment(self):
        self.validate_calls += 1
        if self.validate_error is not None:
            raise self.validate_error

    async def ensure_connected(self):
        self.ensure_connected_calls += 1
        if self.ensure_connected_errors:
            error = self.ensure_connected_errors.pop(0)
            if error is not None:
                raise error
        self.connected = True

    async def ensure_frame_clock_calibration(self):
        self.calibration_calls += 1

    async def set_freshness_barrier(self, reason, options=None):
        if self.barrier_error is not None:
            raise self.barrier_error
        self.barriers.append((reason, options))
        self.events.append(("barrier", reason))
        return 1_000_000

    def subscribe_keyframes(self, listener):
        self.subscribe_calls.append(listener)

        def unsubscribe():
            self.unsubscribe_calls += 1

        return unsubscribe

    def is_connected(self):
        if self.is_connected_results:
            return self.is_connected_results.pop(0)
        return self.connected

    async def get_screenshot_jpeg(self):
        self.screenshot_calls += 1
        self.events.append(("screenshot",))
        result = (
            self.screenshot_results.pop(0)
            if self.screenshot_results
            else jpeg_frame()
        )
        if inspect.isawaitable(result):
            return await result
        if isinstance(result, BaseException):
            raise result
        return result

    async def dispose(self):
        self.dispose_calls += 1
        self.connected = False
        if self.dispose_error is not None:
            raise self.dispose_error

    def get_resolution(self):
        return self.resolution

    def get_latest_raw_keyframe(self):
        return None

    async def decode_raw_keyframe_to_jpeg(self, frame):
        return jpeg_frame()


def freshness_error(message, *, failure_kind="freshness-target",
                    timeout_ms=300, video_bit_rate=4_000_000):
    return ScrcpyFreshFrameUnavailableError(
        message,
        failure_kind=failure_kind,
        timeout_ms=timeout_ms,
        video_bit_rate=video_bit_rate,
    )


def adapter_with_manager(config, manager, backend=None, now=None):
    backend = backend or FakeBackend()
    adapter = ScrcpyDeviceAdapter(
        "device",
        config,
        lambda: backend,
        manager_factory=lambda resolved_backend, options: manager,
        now_ms=now or (lambda: 1_000_000.0),
    )
    adapter._manager = manager
    return adapter


def adapter_with_factory(config, factory, backend=None, now=None, device_id="device"):
    return ScrcpyDeviceAdapter(
        device_id,
        config,
        (lambda: backend) if backend is not None else None,
        manager_factory=factory,
        now_ms=now or (lambda: 1_000_000.0),
    )


async def _wait_until(predicate, timeout=1.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condition was not met before the timeout")


class TestIsEnabled:
    def test_should_return_false_by_default_default_scrcpy_config_enabled(self):
        """should return false by default (DEFAULT_SCRCPY_CONFIG.enabled)."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.is_enabled() is False
        assert adapter.is_enabled() is DEFAULT_SCRCPY_CONFIG["enabled"]

    def test_should_return_false_when_config_enabled_is_false(self):
        """should return false when config.enabled is false."""

        adapter = ScrcpyDeviceAdapter("device", {"enabled": False})
        assert adapter.is_enabled() is False

    def test_should_return_true_when_config_enabled_is_explicitly_true(self):
        """should return true when config.enabled is explicitly true."""

        adapter = ScrcpyDeviceAdapter("device", {"enabled": True})
        assert adapter.is_enabled() is True


class TestGetStatus:
    def test_should_distinguish_disabled_configuration_from_runtime_connection_state(self):
        """should distinguish disabled configuration from runtime connection state."""

        disabled = ScrcpyDeviceAdapter("device", {"enabled": False})
        assert disabled.get_status().enabled is False
        assert disabled.get_status().connected is False
        assert disabled.get_status().last_error is None
        assert disabled.get_status().retry_after is None

        manager = FakeManager(connected=True)
        enabled = adapter_with_manager({"enabled": True}, manager)
        status = enabled.get_status()
        assert status.enabled is True
        assert status.connected is True
        assert status.last_error is None
        assert status.retry_after is None


class TestResolveConfig:
    @pytest.mark.asyncio
    async def test_resolves_and_forwards_an_explicit_encoder_frame_rate(self):
        """resolves and forwards an explicit encoder frame rate."""

        manager = FakeManager()
        calls = []

        def factory(backend, options):
            calls.append((backend, options))
            return manager

        adapter = adapter_with_factory(
            {"enabled": True, "frameRate": 30}, factory
        )
        assert adapter.resolve_config().frame_rate == 30

        await adapter.ensure_manager(DEVICE_INFO)

        assert calls[0][1]["frame_rate"] == 30

    def test_rejects_invalid_encoder_frame_rates_during_resolution(self):
        """rejects invalid encoder frame rates during resolution."""

        adapter = ScrcpyDeviceAdapter("device", {"frameRate": -1})
        with pytest.raises(
            ValueError, match="Invalid scrcpyConfig.frameRate"
        ):
            adapter.resolve_config()

    def test_should_default_max_size_to_0_no_scaling_when_not_explicitly_set(self):
        """should default maxSize to 0 (no scaling) when not explicitly set."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.resolve_config().max_size == 0

    def test_should_use_explicit_max_size_without_auto_calculation(self):
        """should use explicit maxSize without auto-calculation."""

        adapter = ScrcpyDeviceAdapter("device", {"maxSize": 1024})
        assert adapter.resolve_config().max_size == 1024

    def test_should_treat_max_size_0_as_explicit_no_auto_calculation(self):
        """should treat maxSize=0 as explicit (no auto-calculation)."""

        adapter = ScrcpyDeviceAdapter("device", {"maxSize": 0})
        assert adapter.resolve_config().max_size == 0

    @pytest.mark.parametrize(
        "max_size", [-1, 1.5, float("inf"), float("nan")]
    )
    def test_should_reject_invalid_max_size(self, max_size):
        """should reject invalid maxSize %s."""

        adapter = ScrcpyDeviceAdapter("device", {"maxSize": max_size})
        with pytest.raises(
            ValueError,
            match=(
                "Invalid scrcpyConfig.maxSize: expected a non-negative "
                "integer"
            ),
        ):
            adapter.resolve_config()

    def test_should_use_the_default_video_bit_rate_when_not_explicitly_configured(self):
        """should use the default videoBitRate when not explicitly configured."""

        adapter = ScrcpyDeviceAdapter("device", None)
        config = adapter.resolve_config()
        assert config.idle_timeout_ms == DEFAULT_SCRCPY_CONFIG["idle_timeout_ms"]
        assert config.video_bit_rate == DEFAULT_SCRCPY_CONFIG["video_bit_rate"]
        assert config.video_reset_frame_timeout_ms == (
            DEFAULT_SCRCPY_CONFIG["video_reset_frame_timeout_ms"]
        )

    def test_should_honor_a_custom_video_reset_frame_timeout(self):
        """should honor a custom video reset frame timeout."""

        adapter = ScrcpyDeviceAdapter(
            "device", {"videoResetFrameTimeoutMs": 1200}
        )
        assert adapter.resolve_config().video_reset_frame_timeout_ms == 1200

    @pytest.mark.parametrize(
        "timeout", [0, -1, 1.5, float("inf"), float("nan")]
    )
    def test_should_reject_invalid_video_reset_frame_timeout(self, timeout):
        """should reject invalid videoResetFrameTimeoutMs %s."""

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

    @pytest.mark.parametrize(
        "device_id", ["10.84.162.47:36967", "127.0.0.1:5555", "device:5555"]
    )
    def test_should_not_infer_video_bit_rate_from_the_device_endpoint(
        self, device_id
    ):
        """should not infer videoBitRate from the device endpoint %s."""

        adapter = ScrcpyDeviceAdapter(device_id, None)
        assert (
            adapter.resolve_config().video_bit_rate
            == DEFAULT_SCRCPY_CONFIG["video_bit_rate"]
        )

    def test_should_honor_an_explicit_bitrate_on_a_remote_device_endpoint(self):
        """should honor an explicit bitrate on a remote device endpoint."""

        adapter = ScrcpyDeviceAdapter(
            "10.84.162.47:36967", {"videoBitRate": 8_000_000}
        )
        assert adapter.resolve_config().video_bit_rate == 8_000_000

    def test_should_use_custom_idle_timeout_and_video_bit_rate(self):
        """should use custom idleTimeoutMs and videoBitRate."""

        adapter = ScrcpyDeviceAdapter(
            "device", {"idleTimeoutMs": 60000, "videoBitRate": 4000000}
        )
        config = adapter.resolve_config()
        assert config.idle_timeout_ms == 60000
        assert config.video_bit_rate == 4000000

    def test_should_cache_config_same_reference_on_second_call(self):
        """should cache config (same reference on second call)."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.resolve_config() is adapter.resolve_config()

    def test_should_accept_legacy_device_info_without_inferring_config_values(self):
        """should accept legacy device info without inferring config values.

        Python's resolve_config() has no device-info parameter (geometry never
        affected scrcpy configuration in the port).
        """

        adapter = ScrcpyDeviceAdapter("device", None)
        config = adapter.resolve_config()
        assert config.max_size == DEFAULT_SCRCPY_CONFIG["max_size"]
        assert config.video_bit_rate == DEFAULT_SCRCPY_CONFIG["video_bit_rate"]


class TestGetResolution:
    def test_should_return_null_when_no_manager_exists(self):
        """should return null when no manager exists."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.get_resolution() is None

    def test_should_delegate_to_manager_get_resolution(self):
        """should delegate to manager.getResolution()."""

        manager = FakeManager(resolution={"width": 576, "height": 1024})
        adapter = adapter_with_manager(None, manager)
        assert adapter.get_resolution() == {"width": 576, "height": 1024}

    def test_should_return_null_when_manager_get_resolution_returns_null(self):
        """should return null when manager.getResolution() returns null."""

        manager = FakeManager(resolution=None)
        adapter = adapter_with_manager(None, manager)
        assert adapter.get_resolution() is None


class TestGetSize:
    def test_should_return_null_when_no_manager_no_resolution(self):
        """should return null when no manager (no resolution)."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.get_size(DEVICE_INFO) is None

    def test_should_return_size_with_scrcpy_resolution(self):
        """should return Size with scrcpy resolution."""

        manager = FakeManager(resolution={"width": 576, "height": 1024})
        adapter = adapter_with_manager(None, manager)
        assert adapter.get_size(DEVICE_INFO) == {
            "width": 576,
            "height": 1024,
        }


class TestGetScalingRatio:
    def test_should_return_null_when_no_manager(self):
        """should return null when no manager."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert adapter.get_scaling_ratio(1080) is None

    def test_should_calculate_correct_scaling_ratio(self):
        """should calculate correct scaling ratio."""

        manager = FakeManager(resolution={"width": 540, "height": 960})
        adapter = adapter_with_manager(None, manager)
        assert adapter.get_scaling_ratio(1080) == 0.5


class TestEnsureManager:
    @pytest.mark.asyncio
    async def test_should_pass_the_resolved_video_reset_timeout_to_the_manager(self):
        """should pass the resolved video reset timeout to the manager."""

        calls = []

        def factory(backend, options):
            calls.append((backend, options))
            return FakeManager()

        adapter = adapter_with_factory(
            {"enabled": True, "videoResetFrameTimeoutMs": 1200}, factory
        )
        await adapter.ensure_manager(DEVICE_INFO)

        assert calls[0][1]["video_reset_frame_timeout_ms"] == 1200

    @pytest.mark.asyncio
    async def test_should_use_the_local_adb_server_endpoint_by_default(self):
        """should use the local ADB server endpoint by default.

        The Python port drives the ``adb`` binary instead of an ADB server
        TCP connector, so the equivalent default is AdbCommandBackend host
        127.0.0.1 for the requested serial.
        """

        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: FakeManager()
        )
        await adapter.ensure_manager(DEVICE_INFO)

        assert isinstance(adapter._backend, AdbCommandBackend)
        assert adapter._backend.device_id == "device"
        assert adapter._backend.host == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_should_use_one_resolved_adb_backend_for_connection_and_upload(self):
        """should use one resolved ADB backend for connection and upload."""

        backend = FakeBackend()
        resolve_calls = []

        def resolve_backend():
            resolve_calls.append(1)
            return backend

        calls = []

        def factory(resolved_backend, options):
            calls.append((resolved_backend, options))
            return FakeManager()

        adapter = ScrcpyDeviceAdapter(
            "device",
            {"enabled": True},
            resolve_backend,
            manager_factory=factory,
            now_ms=lambda: 1_000_000.0,
        )
        await adapter.ensure_manager(DEVICE_INFO)

        assert len(resolve_calls) == 1
        assert calls[0][0] is backend

        await backend.push(
            "/tmp/scrcpy-server", "/data/local/tmp/scrcpy-server"
        )
        assert backend.push_calls == [
            ("/tmp/scrcpy-server", "/data/local/tmp/scrcpy-server")
        ]

    @pytest.mark.asyncio
    async def test_should_create_its_default_backend_through_the_canonical_adb_factory(self):
        """should create its default backend through the canonical ADB factory.

        Python's canonical factory is AdbCommandBackend(device_id, adb_path).
        """

        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: FakeManager()
        )
        await adapter.ensure_manager(DEVICE_INFO)

        assert isinstance(adapter._backend, AdbCommandBackend)
        assert adapter._backend.device_id == "device"

    @pytest.mark.asyncio
    async def test_should_return_cached_manager_without_re_validation(self):
        """should return cached manager without re-validation."""

        manager = FakeManager()
        adapter = adapter_with_factory(
            None, lambda backend, options: FakeManager()
        )
        adapter._manager = manager

        result = await adapter.ensure_manager(DEVICE_INFO)

        assert result is manager
        assert manager.validate_calls == 0

    @pytest.mark.asyncio
    async def test_should_call_validate_environment_once_before_caching_new_manager(self):
        """should call validateEnvironment once before caching new manager."""

        manager = FakeManager()
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )
        await adapter.ensure_manager(DEVICE_INFO)

        assert manager.validate_calls == 1
        assert adapter._manager is manager

    @pytest.mark.asyncio
    async def test_should_not_cache_manager_when_validate_environment_fails(self):
        """should NOT cache manager when validateEnvironment fails."""

        manager = FakeManager()
        manager.validate_error = RuntimeError("ffmpeg not found")
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )

        with pytest.raises(RuntimeError, match="Failed to initialize Scrcpy"):
            await adapter.ensure_manager(DEVICE_INFO)
        assert adapter._manager is None

    @pytest.mark.asyncio
    async def test_should_include_device_id_in_error_message_on_failure(self):
        """should include device ID in error message on failure."""

        manager = FakeManager()
        manager.validate_error = RuntimeError("test error")
        adapter = adapter_with_factory(
            {"enabled": True},
            lambda backend, options: manager,
            device_id="my-pixel-6",
        )

        with pytest.raises(RuntimeError, match="my-pixel-6"):
            await adapter.ensure_manager(DEVICE_INFO)


class TestScreenshotBase64:
    @pytest.mark.asyncio
    async def test_should_return_base64_image_from_manager(self):
        """should return base64 image from manager.

        Python returns a JPEG data URL directly instead of using the shared
        createImgBase64ByFormat helper mocked upstream.
        """

        manager = FakeManager()
        manager.screenshot_results = [jpeg_frame()]
        adapter = adapter_with_manager({"enabled": True}, manager)

        result = await adapter.screenshot_base64(DEVICE_INFO)

        assert result == jpeg_data_url(jpeg_frame())
        assert manager.screenshot_calls == 1


class TestFrameFreshnessBarriers:
    @pytest.mark.asyncio
    async def test_does_not_discard_an_already_valid_frame_when_observation_starts(self):
        """does not discard an already valid frame when observation starts."""

        manager = FakeManager()
        adapter = adapter_with_manager({"enabled": True}, manager)
        listener = lambda frame: None

        await adapter.subscribe_keyframes(DEVICE_INFO, listener)

        assert manager.ensure_connected_calls == 1
        assert manager.calibration_calls == 1
        assert manager.barriers == []
        assert manager.subscribe_calls == [listener]

    @pytest.mark.asyncio
    async def test_moves_the_barrier_after_an_input_action_completes(self):
        """moves the barrier after an input action completes."""

        manager = FakeManager(connected=True)
        adapter = adapter_with_manager({"enabled": True}, manager)
        adapter._monotonic_time_us_fn = lambda: 10_100_000

        await adapter.mark_action_barrier()

        assert manager.barriers == [
            ("completed input action", {"host_monotonic_us": 10_100_000})
        ]

    @pytest.mark.asyncio
    async def test_keeps_a_successful_input_action_successful_when_clock_sampling_fails(self):
        """keeps a successful input action successful when clock sampling fails."""

        manager = FakeManager(connected=True)
        manager.barrier_error = RuntimeError("dumpsys unavailable")
        adapter = adapter_with_manager({"enabled": True}, manager)

        assert await adapter.mark_action_barrier() is None

        assert manager.dispose_calls == 1
        assert adapter._manager is None
        status = adapter.get_status()
        assert status.last_error == "dumpsys unavailable"
        assert isinstance(status.retry_after, (int, float))

    @pytest.mark.asyncio
    async def test_defers_the_latest_action_barrier_until_a_recovering_stream_is_connected(self):
        """defers the latest action barrier until a recovering stream is connected."""

        manager = FakeManager(connected=False)
        adapter = adapter_with_manager({"enabled": True}, manager)
        times = [10_100_000, 10_200_000]
        adapter._monotonic_time_us_fn = lambda: times.pop(0)

        await adapter.mark_action_barrier()
        await adapter.mark_action_barrier()
        assert manager.barriers == []

        await adapter.screenshot_base64(DEVICE_INFO)

        assert manager.barriers == [
            (
                "completed input action while scrcpy was unavailable",
                {"host_monotonic_us": 10_200_000},
            )
        ]
        barrier_index = manager.events.index(
            ("barrier", "completed input action while scrcpy was unavailable")
        )
        screenshot_index = manager.events.index(("screenshot",))
        assert barrier_index < screenshot_index


class TestInitialize:
    @pytest.mark.asyncio
    async def test_should_call_ensure_manager_and_manager_ensure_connected(self):
        """should call ensureManager and manager.ensureConnected."""

        manager = FakeManager()
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )

        await adapter.initialize(DEVICE_INFO)

        assert manager.validate_calls == 1
        assert manager.ensure_connected_calls == 1
        assert adapter._manager is manager

    @pytest.mark.asyncio
    async def test_deduplicates_concurrent_manager_initialization(self):
        """deduplicates concurrent manager initialization."""

        manager = FakeManager()
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )

        first, second = await asyncio.gather(
            adapter.ensure_manager(DEVICE_INFO),
            adapter.ensure_manager(DEVICE_INFO),
        )

        assert first is manager
        assert second is manager
        assert manager.validate_calls == 1

    @pytest.mark.asyncio
    async def test_should_record_ensure_manager_failures_without_permanently_disabling_scrcpy(self):
        """should record ensureManager failures without permanently disabling scrcpy."""

        manager = FakeManager()
        manager.validate_error = RuntimeError("ffmpeg not found")
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )

        with pytest.raises(RuntimeError):
            await adapter.initialize(DEVICE_INFO)
        status = adapter.get_status()
        assert status.enabled is True
        assert status.connected is False
        assert "ffmpeg not found" in status.last_error
        assert isinstance(status.retry_after, (int, float))
        assert manager.dispose_calls == 1

    @pytest.mark.asyncio
    async def test_should_recover_after_a_transient_ensure_connected_failure(self):
        """should recover after a transient ensureConnected failure."""

        manager = FakeManager()
        manager.ensure_connected_errors = [
            RuntimeError("scrcpy connection failed"),
            None,
        ]
        adapter = adapter_with_factory(
            {"enabled": True}, lambda backend, options: manager
        )

        with pytest.raises(RuntimeError, match="scrcpy connection failed"):
            await adapter.initialize(DEVICE_INFO)
        assert adapter.is_enabled() is False
        assert adapter.get_status().enabled is True

        await adapter.initialize(DEVICE_INFO)
        manager.connected = True

        assert manager.ensure_connected_calls == 2
        status = adapter.get_status()
        assert status.enabled is True
        assert status.connected is True
        assert status.last_error is None
        assert status.retry_after is None


class TestRetryCooldown:
    @pytest.mark.asyncio
    async def test_should_fall_back_during_cooldown_and_retry_on_a_later_screenshot(self):
        """should fall back during cooldown and retry on a later screenshot.

        Python's adapter falls back to ADB inside screenshot_base64() during
        the cooldown, instead of throwing so the caller can fall back.
        """

        clock = [1_000_000.0]
        manager = FakeManager()
        manager.ensure_connected_errors = [RuntimeError("codec not ready")]
        backend = FakeBackend()
        adapter = adapter_with_manager(
            {"enabled": True}, manager, backend=backend,
            now=lambda: clock[0],
        )

        with pytest.raises(RuntimeError, match="codec not ready"):
            await adapter.initialize(DEVICE_INFO)
        result = await adapter.screenshot_base64(DEVICE_INFO)
        assert result == "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nadb"
        ).decode("ascii")
        assert manager.screenshot_calls == 0

        clock[0] += 60_000
        result = await adapter.screenshot_base64(DEVICE_INFO)
        assert result == jpeg_data_url(jpeg_frame())
        assert manager.screenshot_calls == 1
        assert adapter.get_status().last_error is None


class TestFreshnessDiagnostics:
    @pytest.mark.parametrize("video_bit_rate", [4_000_000, 100_000_000])
    def test_does_not_prescribe_bitrate_changes_for_a_freshness_timeout_at_bps(
        self, video_bit_rate
    ):
        """does not prescribe bitrate changes for a freshness timeout at %i bps."""

        message = format_scrcpy_fresh_frame_failure(
            freshness_error("no post-action frame", video_bit_rate=video_bit_rate)
        )

        assert (
            "does not by itself identify bandwidth or the configured video "
            "bitrate as the cause" in message
        )
        assert "lower" not in message.lower()
        assert "--scrcpy-video-bit-rate" not in message
        assert "start with" not in message.lower()

    def test_classifies_a_missing_new_epoch_frame_as_a_startup_failure(self):
        """classifies a missing new-epoch frame as a startup failure."""

        message = format_scrcpy_fresh_frame_failure(
            freshness_error(
                "no initial data frame",
                failure_kind="stream-startup",
                timeout_ms=5_000,
            )
        )

        assert "stream startup or encoder-readiness failure" in message
        assert "lower" not in message.lower()


class TestFreshnessRecovery:
    @pytest.mark.asyncio
    async def test_restarts_a_stale_stream_once_and_returns_the_new_epoch_baseline(self):
        """restarts a stale stream once and returns the new epoch baseline."""

        manager = FakeManager()
        manager.screenshot_results = [
            freshness_error("stale stream closed")
        ]
        adapter = adapter_with_manager({"enabled": True}, manager)

        assert await adapter.screenshot_base64(DEVICE_INFO) == jpeg_data_url(
            jpeg_frame()
        )
        assert manager.screenshot_calls == 2
        assert manager.validate_calls == 0
        assert manager.dispose_calls == 0
        assert adapter.is_enabled() is True
        assert adapter.get_status().last_error is None

    @pytest.mark.asyncio
    async def test_enters_cooldown_when_the_restarted_stream_also_fails_then_retries_with_the_same_manager(self):
        """enters cooldown when the restarted stream also fails, then retries with the same manager."""

        clock = [1_000_000.0]
        manager = FakeManager()
        manager.screenshot_results = [
            freshness_error("first stale stream closed"),
            freshness_error("retry stream closed"),
        ]
        backend = FakeBackend()
        adapter = adapter_with_manager(
            {"enabled": True}, manager, backend=backend,
            now=lambda: clock[0],
        )

        result = await adapter.screenshot_base64(DEVICE_INFO)
        assert result == "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nadb"
        ).decode("ascii")
        assert adapter.is_enabled() is False
        assert adapter._manager is manager
        assert manager.dispose_calls == 0

        clock[0] += 5_000
        assert await adapter.screenshot_base64(DEVICE_INFO) == jpeg_data_url(
            jpeg_frame()
        )
        assert adapter.is_enabled() is True
        assert adapter.get_status().last_error is None
        assert manager.screenshot_calls == 3

    @pytest.mark.asyncio
    async def test_shares_one_in_band_restart_across_concurrent_stale_screenshots(self):
        """shares one in-band restart across concurrent stale screenshots."""

        loop = asyncio.get_running_loop()
        restart_frame = loop.create_future()
        manager = FakeManager()
        manager.screenshot_results = [
            freshness_error("first stale call"),
            freshness_error("second stale call"),
            restart_frame,
        ]
        adapter = adapter_with_manager({"enabled": True}, manager)

        first = asyncio.ensure_future(adapter.screenshot_base64(DEVICE_INFO))
        second = asyncio.ensure_future(adapter.screenshot_base64(DEVICE_INFO))
        await _wait_until(lambda: manager.screenshot_calls == 3)
        restart_frame.set_result(jpeg_frame())

        assert await asyncio.gather(first, second) == [
            jpeg_data_url(jpeg_frame()),
            jpeg_data_url(jpeg_frame()),
        ]
        assert manager.screenshot_calls == 3
        assert manager.ensure_connected_calls == 3

    @pytest.mark.asyncio
    async def test_recognizes_and_retries_freshness_errors_across_duplicated_module_instances(self):
        """recognizes and retries freshness errors across duplicated module instances."""

        manager = FakeManager()
        cross_module_error = RuntimeError("stale stream closed")
        cross_module_error.code = SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE
        manager.screenshot_results = [cross_module_error]
        adapter = adapter_with_manager({"enabled": True}, manager)

        assert await adapter.screenshot_base64(DEVICE_INFO) == jpeg_data_url(
            jpeg_frame()
        )
        assert manager.screenshot_calls == 2
        assert adapter.is_enabled() is True
        assert adapter.get_status().retry_after is None

    @pytest.mark.asyncio
    async def test_reattaches_active_frame_listeners_after_in_band_stream_recovery(self):
        """reattaches active frame listeners after in-band stream recovery."""

        manager = FakeManager()
        manager.is_connected_results = [False, True, False]
        manager.screenshot_results = [
            freshness_error("stale stream closed")
        ]
        adapter = adapter_with_manager({"enabled": True}, manager)
        listener = lambda frame: None

        unsubscribe = await adapter.subscribe_keyframes(
            DEVICE_INFO, listener
        )
        assert await adapter.screenshot_base64(DEVICE_INFO) == jpeg_data_url(
            jpeg_frame()
        )

        assert len(manager.subscribe_calls) == 2
        unsubscribe()
        assert manager.subscribe_calls[-1] is listener

    @pytest.mark.asyncio
    async def test_reattaches_active_frame_listeners_after_a_double_freshness_failure_and_cooldown_reconnect(self):
        """reattaches active frame listeners after a double freshness failure and cooldown reconnect."""

        clock = [1_000_000.0]
        manager = FakeManager()
        manager.is_connected_results = [False, True, False, False]
        manager.screenshot_results = [
            freshness_error("stale stream closed"),
            freshness_error("retry stream closed"),
        ]
        backend = FakeBackend()
        adapter = adapter_with_manager(
            {"enabled": True}, manager, backend=backend,
            now=lambda: clock[0],
        )
        listener = lambda frame: None
        unsubscribe = await adapter.subscribe_keyframes(
            DEVICE_INFO, listener
        )

        result = await adapter.screenshot_base64(DEVICE_INFO)
        assert result == "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nadb"
        ).decode("ascii")
        assert len(manager.subscribe_calls) == 2

        clock[0] += 5_000
        assert await adapter.screenshot_base64(DEVICE_INFO) == jpeg_data_url(
            jpeg_frame()
        )
        assert len(manager.subscribe_calls) == 3
        assert manager.subscribe_calls[-1] is listener
        unsubscribe()


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_should_clear_manager_and_resolved_config(self):
        """should clear manager and resolvedConfig."""

        manager = FakeManager()
        adapter = adapter_with_manager(None, manager)
        adapter.resolve_config()

        await adapter.disconnect()

        assert adapter._manager is None
        assert adapter._resolved_config is None
        assert manager.dispose_calls == 1
        assert adapter.get_status().last_error is None
        assert adapter.get_status().retry_after is None

    @pytest.mark.asyncio
    async def test_should_handle_disconnect_errors_gracefully_no_throw(self):
        """should handle disconnect errors gracefully (no throw)."""

        manager = FakeManager()
        manager.dispose_error = RuntimeError("disconnect failed")
        adapter = adapter_with_manager(None, manager)

        assert await adapter.disconnect() is None
        assert adapter._manager is None

    @pytest.mark.asyncio
    async def test_should_be_no_op_when_no_manager_exists(self):
        """should be no-op when no manager exists."""

        adapter = ScrcpyDeviceAdapter("device", None)
        assert await adapter.disconnect() is None
