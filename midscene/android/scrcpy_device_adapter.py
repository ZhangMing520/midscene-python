"""scrcpy device adapter (upstream scrcpy-device-adapter.ts).

Encapsulates scrcpy configuration normalization, manager lifecycle,
screenshots and resolution so :class:`midscene.android.device.AndroidDevice`
can opt in without changing its existing ADB screenshot path.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from loguru import logger

from midscene.android.scrcpy_manager import (
    DEFAULT_SCRCPY_CONFIG,
    RawKeyframe,
    ScrcpyFreshFrameUnavailableError,
    ScrcpyScreenshotManager,
    ScrcpyStatus,
    is_scrcpy_fresh_frame_unavailable_error,
    resolve_scrcpy_frame_rate,
)

SCRCPY_RETRY_COOLDOWN_MS = 5_000


def _format_js_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_scrcpy_fresh_frame_failure(
    error: ScrcpyFreshFrameUnavailableError,
) -> str:
    """Human-readable freshness diagnostic (upstream helper)."""
    video_bit_rate = getattr(error, "video_bit_rate", None)
    timeout_ms = getattr(error, "timeout_ms", None)
    if not isinstance(timeout_ms, (int, float)) or not math.isfinite(timeout_ms):
        timeout_ms = (
            5_000
            if getattr(error, "failure_kind", None) == "stream-startup"
            else 300
        )

    if getattr(error, "failure_kind", None) == "stream-startup":
        return (
            "The new scrcpy stream did not produce a usable baseline frame "
            f"within {_format_js_number(timeout_ms)}ms. This is a stream "
            "startup or encoder-readiness failure, not evidence that the "
            "configured video bitrate is too high."
        )

    bit_rate_description = ""
    if isinstance(video_bit_rate, (int, float)) and math.isfinite(
        video_bit_rate
    ):
        bit_rate_description = (
            f" Current videoBitRate: {_format_js_number(video_bit_rate)} bps "
            f"({_format_js_number(video_bit_rate / 1_000_000)} Mbps)."
        )
    return (
        "No usable scrcpy frame crossed the active freshness target within "
        f"{_format_js_number(timeout_ms)}ms. This can happen when a static "
        "screen emits no new encoded frame, or when the video stream or "
        "transport is interrupted. This timeout does not by itself identify "
        "bandwidth or the configured video bitrate as the cause."
        f"{bit_rate_description}"
    )


@dataclass(frozen=True)
class ResolvedScrcpyConfig:
    enabled: bool
    max_size: int
    idle_timeout_ms: int
    video_bit_rate: int
    video_reset_frame_timeout_ms: int
    frame_rate: Optional[int] = None

    # camelCase aliases for upstream parity
    @property
    def maxSize(self) -> int:
        return self.max_size

    @property
    def idleTimeoutMs(self) -> int:
        return self.idle_timeout_ms

    @property
    def videoBitRate(self) -> int:
        return self.video_bit_rate

    @property
    def videoResetFrameTimeoutMs(self) -> int:
        return self.video_reset_frame_timeout_ms

    @property
    def frameRate(self) -> Optional[int]:
        return self.frame_rate


def _config_value(
    config: Any, snake_name: str, camel_name: str, default: Any
) -> Any:
    if config is not None:
        for name in (snake_name, camel_name):
            if isinstance(config, Mapping):
                value = config.get(name)
            else:
                value = getattr(config, name, None)
            if value is not None:
                return value
    return default


def _as_js_integer(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
    return int(value)


def _image_base64(mime_type: str, payload: bytes) -> str:
    return (
        f"data:image/{mime_type};base64,"
        f"{base64.b64encode(payload).decode('ascii')}"
    )


def _default_manager_factory(backend: Any, options: Mapping[str, Any]) -> Any:
    return ScrcpyScreenshotManager(
        backend,
        getattr(backend, "push", None),
        options,
    )


class ScrcpyDeviceAdapter:
    """Adapter encapsulating all scrcpy-related logic for an Android device."""

    def __init__(
        self,
        device_id: str,
        scrcpy_config: Optional[Mapping[str, Any]] = None,
        resolve_adb_backend: Optional[Callable[[], Any]] = None,
        *,
        manager_factory: Optional[
            Callable[[Any, Mapping[str, Any]], Any]
        ] = None,
        monotonic_time_us: Optional[Callable[[], int]] = None,
        now_ms: Optional[Callable[[], float]] = None,
        adb_path: Optional[str] = None,
    ) -> None:
        self.device_id = device_id
        self._scrcpy_config = scrcpy_config
        self._adb_path = adb_path
        self._resolve_adb_backend = (
            resolve_adb_backend or self._create_default_backend
        )
        self._manager_factory = manager_factory or _default_manager_factory
        self._monotonic_time_us_fn = (
            monotonic_time_us
            or (lambda: time.monotonic_ns() // 1000)
        )
        self._now_ms = now_ms or (lambda: time.time() * 1000)

        self._manager: Any = None
        self._manager_task: Optional[asyncio.Task] = None
        self._resolved_config: Optional[ResolvedScrcpyConfig] = None
        self._last_error: Optional[str] = None
        self._retry_after: Optional[float] = None
        self._freshness_restart_task: Optional[asyncio.Task] = None
        self._lifecycle_generation = 0
        self._pending_action_barrier_at_host_us: Optional[int] = None
        self._keyframe_listeners: set = set()
        self._keyframe_unsubscribers: Dict[Any, Dict[str, Any]] = {}
        self._backend: Any = None

    # -- configuration ----------------------------------------------------

    @staticmethod
    async def create_android_adb(
        adb_exec_timeout: float = 60_000,
        device_id: Optional[str] = None,
    ) -> Any:
        """Create the ADB client used by the scrcpy backend (upstream)."""
        from midscene.android.adb import create_android_adb

        return await create_android_adb(
            adb_exec_timeout=adb_exec_timeout,
            device_id=device_id,
        )

    def _create_default_backend(self) -> Any:
        from midscene.android.scrcpy_manager import AdbCommandBackend

        return AdbCommandBackend(self.device_id, adb_path=self._adb_path)

    def is_configured(self) -> bool:
        return bool(
            _config_value(
                self._scrcpy_config,
                "enabled",
                "enabled",
                DEFAULT_SCRCPY_CONFIG["enabled"],
            )
        )

    def is_enabled(self) -> bool:
        if not self.is_configured():
            return False
        return self._retry_after is None or self._now_ms() >= self._retry_after

    def get_status(self) -> ScrcpyStatus:
        manager = self._manager
        connected = bool(manager is not None and manager.is_connected())
        return ScrcpyStatus(
            enabled=self.is_configured(),
            connected=connected,
            last_error=self._last_error,
            retry_after=self._retry_after,
        )

    def resolve_config(self) -> ResolvedScrcpyConfig:
        if self._resolved_config is not None:
            return self._resolved_config

        max_size_value = _config_value(
            self._scrcpy_config,
            "max_size",
            "maxSize",
            DEFAULT_SCRCPY_CONFIG["max_size"],
        )
        max_size = _as_js_integer(max_size_value)
        if max_size is None or max_size < 0:
            raise ValueError(
                "Invalid scrcpyConfig.maxSize: expected a non-negative "
                f"integer, received {_format_js_number(max_size_value)}"
            )

        video_reset_value = _config_value(
            self._scrcpy_config,
            "video_reset_frame_timeout_ms",
            "videoResetFrameTimeoutMs",
            DEFAULT_SCRCPY_CONFIG["video_reset_frame_timeout_ms"],
        )
        video_reset_timeout = _as_js_integer(video_reset_value)
        if video_reset_timeout is None or video_reset_timeout <= 0:
            raise ValueError(
                "Invalid scrcpyConfig.videoResetFrameTimeoutMs: expected a "
                f"positive integer, received {_format_js_number(video_reset_value)}"
            )

        self._resolved_config = ResolvedScrcpyConfig(
            enabled=self.is_configured(),
            max_size=max_size,
            idle_timeout_ms=int(
                _config_value(
                    self._scrcpy_config,
                    "idle_timeout_ms",
                    "idleTimeoutMs",
                    DEFAULT_SCRCPY_CONFIG["idle_timeout_ms"],
                )
            ),
            video_bit_rate=int(
                _config_value(
                    self._scrcpy_config,
                    "video_bit_rate",
                    "videoBitRate",
                    DEFAULT_SCRCPY_CONFIG["video_bit_rate"],
                )
            ),
            video_reset_frame_timeout_ms=video_reset_timeout,
            frame_rate=resolve_scrcpy_frame_rate(
                _config_value(
                    self._scrcpy_config,
                    "frame_rate",
                    "frameRate",
                    None,
                )
            ),
        )
        return self._resolved_config

    # -- failure bookkeeping ---------------------------------------------

    def _record_failure(self, error: BaseException) -> None:
        self._last_error = str(error)
        self._retry_after = self._now_ms() + SCRCPY_RETRY_COOLDOWN_MS

    def _clear_failure(self) -> None:
        self._last_error = None
        self._retry_after = None

    def _ensure_retry_ready(self) -> None:
        if self._retry_after is None or self._now_ms() >= self._retry_after:
            return
        timestamp = (
            time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(self._retry_after / 1000)
            )
            + "Z"
        )
        raise RuntimeError(
            f"scrcpy retry is cooling down until {timestamp}. Last error: "
            f"{self._last_error}"
        )

    # -- manager lifecycle ------------------------------------------------

    async def ensure_manager(self, device_info: Any = None) -> Any:
        if self._manager is not None:
            return self._manager

        if self._manager_task is None:
            self._manager_task = asyncio.ensure_future(
                self._create_manager(device_info)
            )
        task = self._manager_task
        try:
            return await asyncio.shield(task)
        finally:
            if self._manager_task is task and task.done():
                self._manager_task = None

    async def _create_manager(self, device_info: Any = None) -> Any:
        logger.debug("Initializing Scrcpy manager...")
        generation = self._lifecycle_generation
        manager = None
        try:
            if self._backend is None:
                backend_result = self._resolve_adb_backend()
                if inspect.isawaitable(backend_result):
                    backend_result = await backend_result
                self._backend = backend_result

            config = self.resolve_config()
            manager = self._manager_factory(
                self._backend,
                {
                    "frame_rate": config.frame_rate,
                    "max_size": config.max_size,
                    "video_bit_rate": config.video_bit_rate,
                    "idle_timeout_ms": config.idle_timeout_ms,
                    "video_reset_frame_timeout_ms": (
                        config.video_reset_frame_timeout_ms
                    ),
                },
            )
            await manager.validate_environment()

            if generation != self._lifecycle_generation:
                raise RuntimeError(
                    "Scrcpy manager initialization was superseded by device "
                    "cleanup"
                )

            self._manager = manager
            logger.debug("Scrcpy manager initialized")
            return manager
        except Exception as error:  # noqa: BLE001 - wrapped with context
            try:
                if manager is not None:
                    dispose = getattr(manager, "dispose", None)
                    if dispose is not None:
                        result = dispose()
                        if inspect.isawaitable(result):
                            await result
                elif self._backend is not None:
                    close = getattr(self._backend, "close", None)
                    if close is not None:
                        result = close()
                        if inspect.isawaitable(result):
                            await result
            except Exception as cleanup_error:  # noqa: BLE001
                logger.debug(
                    "Failed to clean up Scrcpy manager initialization: "
                    f"{cleanup_error}"
                )
            logger.debug(f"Failed to initialize Scrcpy manager: {error}")
            raise RuntimeError(
                f"Failed to initialize Scrcpy for device {self.device_id}. "
                "Ensure ADB server is running and device is connected. "
                f"Error: {error}"
            ) from error

    async def _ensure_connected_manager(self, device_info: Any = None) -> Any:
        manager = await self.ensure_manager(device_info)
        was_connected = manager.is_connected()
        await manager.ensure_connected()
        self._attach_keyframe_listeners(manager, force=not was_connected)
        return manager

    async def initialize(self, device_info: Any = None) -> None:
        try:
            manager = await self._ensure_connected_manager(device_info)
            await self._apply_pending_action_barrier(manager)
            self._clear_failure()
        except Exception as error:  # noqa: BLE001 - recorded then re-raised
            self._record_failure(error)
            raise

    # -- screenshots ------------------------------------------------------

    @staticmethod
    def _jpeg_buffer_to_base64(screenshot_buffer: bytes) -> str:
        return _image_base64("jpeg", screenshot_buffer)

    async def screenshot_base64(
        self,
        device_info: Any = None,
        *,
        fallback: Optional[Callable[[], Any]] = None,
    ) -> str:
        """Capture via scrcpy, falling back to the ADB path when unavailable.

        ``fallback`` may be a sync/async callable returning either a raw base64
        string or a data URL.  When omitted the ADB backend's ``screencap_png``
        is used.
        """
        if not self.is_enabled():
            return await self._fallback_screenshot(fallback)

        try:
            manager = await self._ensure_connected_manager(device_info)
            await self._apply_pending_action_barrier(manager)
            screenshot_buffer = await manager.get_screenshot_jpeg()
            self._clear_failure()
            return self._jpeg_buffer_to_base64(screenshot_buffer)
        except Exception as error:  # noqa: BLE001 - fallback path
            if not is_scrcpy_fresh_frame_unavailable_error(error):
                logger.warning(
                    "Scrcpy screenshot failed, falling back to standard ADB "
                    f"method. Error: {error}"
                )
                self._record_failure(error)
                return await self._fallback_screenshot(fallback, error)

            logger.debug(
                "Scrcpy freshness target was unavailable; restarting the "
                f"stream once before ADB fallback: {error}"
            )
            try:
                screenshot_buffer = await self._restart_and_capture_once(
                    device_info
                )
                self._clear_failure()
                logger.debug(
                    "Scrcpy screenshot recovered on a new stream epoch"
                )
                return self._jpeg_buffer_to_base64(screenshot_buffer)
            except Exception as retry_error:  # noqa: BLE001 - fallback path
                self._keyframe_unsubscribers.clear()
                self._record_failure(retry_error)
                logger.warning(
                    "Scrcpy screenshot failed after restart, falling back to "
                    f"standard ADB method. Error: {retry_error}"
                )
                return await self._fallback_screenshot(
                    fallback, retry_error
                )

    async def _fallback_screenshot(
        self,
        fallback: Optional[Callable[[], Any]] = None,
        error: Optional[BaseException] = None,
    ) -> str:
        if fallback is not None:
            result = fallback()
            if inspect.isawaitable(result):
                result = await result
            return result

        if self._backend is None:
            try:
                backend_result = self._resolve_adb_backend()
                if inspect.isawaitable(backend_result):
                    backend_result = await backend_result
                self._backend = backend_result
            except Exception:
                if error is not None:
                    raise error
                raise

        screencap = getattr(self._backend, "screencap_png", None)
        if screencap is None:
            if error is not None:
                raise error
            raise RuntimeError(
                "scrcpy is unavailable and no ADB screenshot fallback exists"
            )
        png = screencap()
        if inspect.isawaitable(png):
            png = await png
        return _image_base64("png", png)

    async def _restart_and_capture_once(self, device_info: Any = None) -> bytes:
        if self._freshness_restart_task is not None:
            return await asyncio.shield(self._freshness_restart_task)

        generation = self._lifecycle_generation

        async def restart() -> bytes:
            manager = await self._ensure_connected_manager(device_info)
            await self._apply_pending_action_barrier(manager)
            if generation != self._lifecycle_generation:
                raise RuntimeError(
                    "Scrcpy freshness restart was cancelled by cleanup"
                )
            return await manager.get_screenshot_jpeg()

        task = asyncio.ensure_future(restart())
        self._freshness_restart_task = task
        try:
            return await asyncio.shield(task)
        finally:
            if self._freshness_restart_task is task and task.done():
                self._freshness_restart_task = None

    # -- keyframes --------------------------------------------------------

    async def subscribe_keyframes(
        self,
        device_info: Any,
        listener: Callable[[RawKeyframe], Any],
    ) -> Callable[[], None]:
        self._ensure_retry_ready()
        self._keyframe_listeners.add(listener)

        try:
            manager = await self._ensure_connected_manager(device_info)
            await self._apply_pending_action_barrier(manager)
            await manager.ensure_frame_clock_calibration()
            self._clear_failure()

            def unsubscribe() -> None:
                self._keyframe_listeners.discard(listener)
                subscription = self._keyframe_unsubscribers.pop(
                    listener, None
                )
                if subscription is not None:
                    subscription["unsubscribe"]()

            return unsubscribe
        except Exception as error:  # noqa: BLE001 - cleanup then re-raise
            self._keyframe_listeners.discard(listener)
            subscription = self._keyframe_unsubscribers.pop(listener, None)
            if subscription is not None:
                subscription["unsubscribe"]()
            self._record_failure(error)
            raise

    def get_latest_raw_keyframe(self) -> Optional[RawKeyframe]:
        if self._manager is None:
            return None
        return self._manager.get_latest_raw_keyframe()

    def _attach_keyframe_listener(
        self, manager: Any, listener: Callable[[RawKeyframe], Any], force: bool
    ) -> None:
        existing = self._keyframe_unsubscribers.get(listener)
        if not force and existing is not None and existing["manager"] is manager:
            return
        if existing is not None:
            existing["unsubscribe"]()
        self._keyframe_unsubscribers[listener] = {
            "manager": manager,
            "unsubscribe": manager.subscribe_keyframes(listener),
        }

    def _attach_keyframe_listeners(
        self, manager: Any, force: bool
    ) -> None:
        for listener in list(self._keyframe_listeners):
            self._attach_keyframe_listener(manager, listener, force)

    async def decode_raw_keyframe_to_jpeg_base64(
        self, frame: RawKeyframe
    ) -> str:
        if self._manager is None:
            raise RuntimeError("scrcpy manager is not initialized")
        jpeg_buffer = await self._manager.decode_raw_keyframe_to_jpeg(frame)
        return self._jpeg_buffer_to_base64(jpeg_buffer)

    # -- freshness barrier -------------------------------------------------

    async def _apply_pending_action_barrier(self, manager: Any) -> None:
        action_completed_at_host_us = self._pending_action_barrier_at_host_us
        if action_completed_at_host_us is None:
            return
        await manager.set_freshness_barrier(
            "completed input action while scrcpy was unavailable",
            {"host_monotonic_us": action_completed_at_host_us},
        )
        if (
            self._pending_action_barrier_at_host_us
            == action_completed_at_host_us
        ):
            self._pending_action_barrier_at_host_us = None

    def _monotonic_time_us(self) -> int:
        return self._monotonic_time_us_fn()

    def _defer_action_barrier(self, action_completed_at_host_us: int) -> None:
        if (
            self._pending_action_barrier_at_host_us is None
            or action_completed_at_host_us
            > self._pending_action_barrier_at_host_us
        ):
            self._pending_action_barrier_at_host_us = action_completed_at_host_us

    async def mark_action_barrier(self) -> None:
        action_completed_at_host_us = self._monotonic_time_us()
        manager = self._manager
        if manager is None or not manager.is_connected():
            self._defer_action_barrier(action_completed_at_host_us)
            return

        try:
            await manager.set_freshness_barrier(
                "completed input action",
                {"host_monotonic_us": action_completed_at_host_us},
            )
            if (
                self._pending_action_barrier_at_host_us is not None
                and self._pending_action_barrier_at_host_us
                <= action_completed_at_host_us
            ):
                self._pending_action_barrier_at_host_us = None
            self._clear_failure()
        except Exception as error:  # noqa: BLE001 - action stays successful
            self._defer_action_barrier(action_completed_at_host_us)
            self._record_failure(error)
            logger.debug(
                "Unable to mark scrcpy action barrier; disabling this stream: "
                f"{error}"
            )
            try:
                await manager.dispose()
            except Exception as disconnect_error:  # noqa: BLE001
                logger.debug(
                    "Error disconnecting scrcpy after barrier failure: "
                    f"{disconnect_error}"
                )
            finally:
                if self._manager is manager:
                    self._manager = None

    # -- size -------------------------------------------------------------

    def get_resolution(self) -> Optional[Dict[str, int]]:
        if self._manager is None:
            return None
        return self._manager.get_resolution()

    def get_size(self, device_info: Any = None) -> Optional[Dict[str, int]]:
        resolution = self.get_resolution()
        if resolution is None:
            return None
        logger.debug(
            f"Using scrcpy resolution: {resolution['width']}x"
            f"{resolution['height']}"
        )
        return {"width": resolution["width"], "height": resolution["height"]}

    def get_scaling_ratio(self, physical_width: int) -> Optional[float]:
        resolution = self.get_resolution()
        if resolution is None or physical_width == 0:
            return None
        return resolution["width"] / physical_width

    async def size(self, device_info: Any = None) -> Dict[str, int]:
        size = self.get_size(device_info)
        if size is not None:
            return size
        backend = self._backend
        if backend is None:
            backend_result = self._resolve_adb_backend()
            if inspect.isawaitable(backend_result):
                backend_result = await backend_result
            backend = backend_result
            self._backend = backend
        screen_size = getattr(backend, "screen_size", None)
        if screen_size is None:
            raise RuntimeError("scrcpy resolution is unavailable")
        result = screen_size()
        if inspect.isawaitable(result):
            result = await result
        return result

    # -- teardown ---------------------------------------------------------

    async def disconnect(self) -> None:
        self._lifecycle_generation += 1
        self._pending_action_barrier_at_host_us = None
        for subscription in list(self._keyframe_unsubscribers.values()):
            subscription["unsubscribe"]()
        self._keyframe_unsubscribers.clear()
        self._keyframe_listeners.clear()

        if self._freshness_restart_task is not None:
            with contextlib.suppress(BaseException):
                await self._freshness_restart_task

        if self._manager_task is not None:
            with contextlib.suppress(BaseException):
                await self._manager_task

        if self._manager is not None:
            try:
                await self._manager.dispose()
            except Exception as error:  # noqa: BLE001
                logger.debug(f"Error disconnecting scrcpy: {error}")
            self._manager = None
        self._resolved_config = None
        self._clear_failure()


__all__ = [
    "ResolvedScrcpyConfig",
    "SCRCPY_RETRY_COOLDOWN_MS",
    "ScrcpyDeviceAdapter",
    "ScrcpyStatus",
    "format_scrcpy_fresh_frame_failure",
]
