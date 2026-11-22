"""scrcpy screenshot manager (upstream packages/android/src/scrcpy-manager.ts).

The upstream TypeScript implementation drives scrcpy through
``@yume-chan/adb-scrcpy``, which owns the ADB transport, the scrcpy server
process and the video/control sockets.  The Python SDK cannot add that
dependency, so this module implements the wire protocol directly on top of the
``adb`` binary:

* push ``scrcpy-server`` to ``/data/local/tmp/scrcpy-server.jar``;
* create a ``adb forward`` tunnel for the abstract ``scrcpy_<scid>`` socket;
* launch ``app_process ... com.genymobile.scrcpy.Server <version> ...``;
* read the H.264 packet stream (``send_frame_meta=true``), extract IDR
  keyframes and decode them to JPEG with ``ffmpeg``.

Everything parity-relevant from upstream is preserved: the device-clock frame
freshness barrier, ``RawKeyframe``/``ScrcpyFreshFrameUnavailableError``
contracts, keyframe subscribers, idle teardown, in-band video reset hooks and
the exact user-facing error messages.

Deliberate simplifications (documented instead of silently ignored):

* The scrcpy control channel is not multiplexed here; ``reset_video`` is
  supported only when a controller object is injected (tests / future
  transports).  Without it the manager reports the same
  ``Scrcpy control channel is unavailable for video reset`` error as upstream.
* Decoding uses one synchronous ffmpeg run per requested keyframe, like
  upstream, but is executed in an asyncio subprocess so the event loop stays
  free.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import math
import os
import re
import struct
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    TypedDict,
)

from loguru import logger

from midscene.android.adb import resolve_adb_executable, run_adb_command
from midscene.android.resource_path import resolve_external_resource_path
from midscene.shared.env import get_midscene_run_dir
from midscene.shared.img.info import encoded_image_info_of_buffer

# ---------------------------------------------------------------------------
# Constants (mirrors upstream scrcpy-manager.ts)
# ---------------------------------------------------------------------------

# H.264 NAL unit types
NAL_TYPE_IDR = 5  # IDR slice (keyframe/I-frame)
NAL_TYPE_SPS = 7  # Sequence Parameter Set
NAL_TYPE_PPS = 8  # Picture Parameter Set
NAL_TYPE_MASK = 0x1F  # Lower 5 bits

# Configuration defaults
DEFAULT_MAX_SIZE = 0  # 0 = no scaling, keep original resolution
DEFAULT_VIDEO_BIT_RATE = 100_000_000  # 100Mbps all-I-frame over local ADB
MAX_VIDEO_BIT_RATE = 100_000_000  # Safe upper limit for Android H.264 encoders
DEFAULT_IDLE_TIMEOUT_MS = 30_000

# Timeouts and limits
MAX_KEYFRAME_WAIT_MS = 5_000
FRESH_FRAME_TIMEOUT_MS = 300
VIDEO_RESET_DELAY_MS = 10
DEFAULT_VIDEO_RESET_FRAME_TIMEOUT_MS = 800
KEYFRAME_POLL_INTERVAL_MS = 200
MAX_SCAN_BYTES = 1_000
MAX_SERVER_OUTPUT_LINES = 100
SERVER_OUTPUT_DRAIN_TIMEOUT_MS = 500
MAX_FRAME_AGE_US = 500_000
FRAME_FRESHNESS_WARN_INTERVAL_MS = 5_000
DEVICE_UPTIME_COMMAND = ["dumpsys", "power"]

# Busy-loop detection thresholds
BUSY_LOOP_WINDOW_MS = 1_000
BUSY_LOOP_MAX_READS = 500
BUSY_LOOP_COOLDOWN_MS = 50
BUSY_LOOP_WARN_INTERVAL_MS = 5_000

# scrcpy server acquisition / protocol
SCRCPY_PROTOCOL_VERSION = "3.3.3"
SCRCPY_SERVER_VERSION_TAG = f"v{SCRCPY_PROTOCOL_VERSION}"
SCRCPY_SERVER_VERSION_FILENAME = "scrcpy-server.version"
DEFAULT_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
SCRCPY_SERVER_FILE_NAME = "scrcpy-server"

SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE = "ERR_SCRCPY_FRESH_FRAME_UNAVAILABLE"

_JS_MAX_INT32 = 2_147_483_647
_FRAME_CONFIG_PTS = 0xFFFFFFFFFFFFFFFF  # scrcpy's "configuration packet" marker

# Known scrcpy 2.x/3.x video codec ids written as a fourcc in the header.
_CODEC_IDS = (b"h264", b"h265", b"av1\x00")

_FFMPEG_ARGS = [
    "-f",
    "h264",
    "-i",
    "pipe:0",
    "-vframes",
    "1",
    "-f",
    "image2pipe",
    "-vcodec",
    "mjpeg",
    "-q:v",
    "5",
    "-loglevel",
    "error",
    "pipe:1",
]


class ScrcpyConfig(TypedDict, total=False):
    """User-facing scrcpy configuration (upstream ``scrcpyConfig``).

    Both the Pythonic snake_case keys and the upstream camelCase keys are
    accepted by :class:`ScrcpyDeviceAdapter`; this TypedDict documents both.
    """

    enabled: bool
    frame_rate: int
    max_size: int
    video_bit_rate: int
    idle_timeout_ms: int
    video_reset_frame_timeout_ms: int

    # Upstream aliases
    frameRate: int
    maxSize: int
    videoBitRate: int
    idleTimeoutMs: int
    videoResetFrameTimeoutMs: int


DEFAULT_SCRCPY_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "max_size": DEFAULT_MAX_SIZE,
    "idle_timeout_ms": DEFAULT_IDLE_TIMEOUT_MS,
    "video_bit_rate": DEFAULT_VIDEO_BIT_RATE,
    "video_reset_frame_timeout_ms": DEFAULT_VIDEO_RESET_FRAME_TIMEOUT_MS,
}

_MISSING = object()


def _coerce_int(value: Any) -> Optional[int]:
    """Return an int for JS-integer-like values, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def _format_js_number(value: Any) -> str:
    """Format a number the way JavaScript ``String(number)`` would."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def resolve_scrcpy_frame_rate(frame_rate: Optional[float] = None) -> Optional[int]:
    """Validate ``scrcpyConfig.frameRate`` (upstream resolveScrcpyFrameRate)."""
    if frame_rate is None:
        return None
    resolved = _coerce_int(frame_rate)
    if (
        resolved is None
        or resolved <= 0
        or resolved > _JS_MAX_INT32
    ):
        raise ValueError(
            "Invalid scrcpyConfig.frameRate: expected a positive 32-bit "
            f"integer, received {_format_js_number(frame_rate)}"
        )
    return resolved


def _option(options: Any, *names: str, default: Any = _MISSING) -> Any:
    """Read an option from a mapping/object using aliases, ignoring None."""
    if options is not None:
        for name in names:
            if isinstance(options, Mapping):
                value = options.get(name, _MISSING)
            else:
                value = getattr(options, name, _MISSING)
            if value is not _MISSING and value is not None:
                return value
    if default is _MISSING:
        raise KeyError(names[0])
    return default


@dataclass(frozen=True)
class ResolvedScrcpyOptions:
    """Required options after applying defaults."""

    frame_rate: Optional[int]
    max_size: int
    video_bit_rate: int
    idle_timeout_ms: int
    video_reset_frame_timeout_ms: int

    # camelCase aliases for upstream parity
    @property
    def frameRate(self) -> Optional[int]:
        return self.frame_rate

    @property
    def maxSize(self) -> int:
        return self.max_size

    @property
    def videoBitRate(self) -> int:
        return self.video_bit_rate

    @property
    def idleTimeoutMs(self) -> int:
        return self.idle_timeout_ms

    @property
    def videoResetFrameTimeoutMs(self) -> int:
        return self.video_reset_frame_timeout_ms


@dataclass
class RawKeyframe:
    """A raw (not yet decoded) H.264 keyframe emitted by the scrcpy stream."""

    data: bytes
    """Raw H.264 keyframe data WITHOUT the SPS/PPS header."""

    header: bytes
    """SPS/PPS header active when this frame was produced (needed to decode)."""

    pts_us: Optional[int] = None
    """Device-monotonic capture timestamp forwarded by scrcpy."""

    estimated_age_ms: Optional[float] = None
    """Estimated frame age when the packet reached the host."""

    stream_epoch: Any = None
    """Encoder epoch that produced this frame."""

    captured_at: float = 0.0


@dataclass
class ScrcpyStatus:
    enabled: bool
    connected: bool
    last_error: Optional[str]
    retry_after: Optional[float]


@dataclass
class DeviceClockCalibration:
    device_uptime_us: int
    host_monotonic_us: int
    host_wall_time_ms: float
    round_trip_us: int


@dataclass
class FrameAgeEstimate:
    estimated_age_us: int
    calibration_uncertainty_us: int
    upper_bound_us: int


class ScrcpyFreshFrameUnavailableError(RuntimeError):
    """Raised when no usable fresh frame can be obtained from scrcpy."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: str,
        timeout_ms: float,
        video_bit_rate: float,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.name = "ScrcpyFreshFrameUnavailableError"
        self.code = SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE
        self.failure_kind = failure_kind
        self.timeout_ms = timeout_ms
        self.video_bit_rate = video_bit_rate
        self.cause = cause


class ScrcpyFrameWaitTimeoutError(RuntimeError):
    def __init__(self, message: str, timeout_ms: float) -> None:
        super().__init__(message)
        self.name = "ScrcpyFrameWaitTimeoutError"
        self.timeout_ms = timeout_ms


def is_scrcpy_fresh_frame_unavailable_error(error: Any) -> bool:
    """Duck-typed check that also accepts cross-module/deserialized errors."""
    if isinstance(error, Mapping):
        return error.get("code") == SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE
    return getattr(error, "code", None) == SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE


# ---------------------------------------------------------------------------
# Device clock / H.264 helpers
# ---------------------------------------------------------------------------

_UPTIME_PATTERN = re.compile(
    r"mLastWakeTime=(\d+)\s+\((?:(\d+) ms ago|in (\d+) ms|now)\)"
)


def parse_device_uptime_ms(output: str) -> int:
    """Reconstruct SystemClock.uptimeMillis() from ``dumpsys power``."""
    match = _UPTIME_PATTERN.search(output)
    if not match:
        raise ValueError(
            "Unable to read Android device uptime from dumpsys power: "
            f"{output.strip() or '<empty output>'}"
        )

    reference_ms = int(match.group(1))
    if match.group(2):
        return reference_ms + int(match.group(2))
    if match.group(3):
        return reference_ms - int(match.group(3))
    return reference_ms


def _is_key_frame_nal_type(nal_unit_type: int) -> bool:
    return nal_unit_type in (NAL_TYPE_IDR, NAL_TYPE_SPS, NAL_TYPE_PPS)


def detect_h264_keyframe(buffer: bytes) -> bool:
    """Detect an H.264 IDR/SPS/PPS NAL in the first ``MAX_SCAN_BYTES``."""
    scan_limit = min(len(buffer) - 4, MAX_SCAN_BYTES)
    index = 0
    while index < scan_limit:
        if (
            buffer[index] == 0x00
            and buffer[index + 1] == 0x00
            and buffer[index + 2] == 0x00
            and buffer[index + 3] == 0x01
        ):
            if _is_key_frame_nal_type(buffer[index + 4] & NAL_TYPE_MASK):
                return True
        elif (
            buffer[index] == 0x00
            and buffer[index + 1] == 0x00
            and buffer[index + 2] == 0x01
        ):
            if _is_key_frame_nal_type(buffer[index + 3] & NAL_TYPE_MASK):
                return True
        index += 1
    return False


def _now_ms() -> float:
    # Deadlines are monotonic: wall-clock jumps must not move capture windows.
    return time.monotonic() * 1000.0


# ---------------------------------------------------------------------------
# scrcpy-server acquisition
# ---------------------------------------------------------------------------

def should_download_scrcpy_server(
    existing_version: Optional[str],
    expected_version: str = SCRCPY_SERVER_VERSION_TAG,
) -> bool:
    return (existing_version or "").strip() != expected_version


def get_scrcpy_server_download_url(
    version: str = SCRCPY_SERVER_VERSION_TAG,
) -> str:
    return (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        f"{version}/scrcpy-server-{version}"
    )


def _default_http_get(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _read_existing_server(path: Path) -> Optional[str]:
    try:
        if path.is_file() and path.stat().st_size > 0:
            return str(path)
    except OSError:
        return None
    return None


def ensure_scrcpy_server(
    explicit_path: Optional[str] = None,
    cache_dir: Optional[str] = None,
    version: str = SCRCPY_SERVER_VERSION_TAG,
    download: bool = True,
    url: Optional[str] = None,
    http_get: Optional[Callable[[str, float], bytes]] = None,
    timeout: float = 120.0,
) -> str:
    """Resolve the local scrcpy-server jar, downloading it to a cache dir.

    Resolution order: explicit path, ``MIDSCENE_SCRCPY_SERVER_PATH``, packaged
    ``midscene/android/bin/scrcpy-server``, then the cache directory.  When no
    local copy exists the release asset is downloaded (configurable through
    ``url``/``MIDSCENE_SCRCPY_SERVER_URL``).  A missing jar is never reported
    as available: this raises instead.
    """
    explicit = explicit_path or os.environ.get("MIDSCENE_SCRCPY_SERVER_PATH")
    if explicit:
        resolved = resolve_external_resource_path(explicit)
        local = _read_existing_server(Path(resolved))
        if local is None:
            raise FileNotFoundError(
                f"scrcpy-server jar was not found at {explicit}. "
                "Download it from "
                f"{get_scrcpy_server_download_url(version)} and set "
                "MIDSCENE_SCRCPY_SERVER_PATH to its location."
            )
        return local

    packaged = (
        Path(__file__).resolve().parent / "bin" / SCRCPY_SERVER_FILE_NAME
    )
    packaged_path = _read_existing_server(packaged)
    if packaged_path is not None:
        return resolve_external_resource_path(packaged_path)

    if cache_dir is None:
        env_cache = os.environ.get("MIDSCENE_SCRCPY_SERVER_DIR")
        cache_dir = env_cache or get_midscene_run_dir("scrcpy")
    cache_path = Path(cache_dir)
    server_file = cache_path / SCRCPY_SERVER_FILE_NAME
    existing = _read_existing_server(server_file)
    if existing is not None:
        return existing

    download_url = (
        url
        or os.environ.get("MIDSCENE_SCRCPY_SERVER_URL")
        or get_scrcpy_server_download_url(version)
    )
    if not download:
        raise FileNotFoundError(
            f"scrcpy-server jar was not found at {server_file}. "
            f"Download it from {download_url} and set "
            "MIDSCENE_SCRCPY_SERVER_PATH to its location."
        )

    cache_path.mkdir(parents=True, exist_ok=True)
    partial_file = server_file.with_name(server_file.name + ".part")
    getter = http_get or _default_http_get
    try:
        try:
            data = getter(download_url, timeout)
        except TypeError:
            # Tolerate simple one-argument download callables.
            data = getter(download_url)
        if inspect.isawaitable(data):
            # Keep this helper synchronous; callers that need async acquisition
            # can inject an async wrapper via an executor.
            raise TypeError(
                "ensure_scrcpy_server requires a synchronous http_get callable"
            )
    except Exception as error:  # noqa: BLE001 - re-raised with guidance
        raise RuntimeError(
            f"Failed to download the scrcpy-server jar from {download_url}: "
            f"{error}. Download it manually and set "
            "MIDSCENE_SCRCPY_SERVER_PATH, or place it at "
            f"{server_file}."
        ) from error

    if not data:
        raise RuntimeError(
            f"Downloaded an empty scrcpy-server jar from {download_url}. "
            f"Place a valid jar at {server_file} or set "
            "MIDSCENE_SCRCPY_SERVER_PATH."
        )

    partial_file.write_bytes(data)
    os.replace(partial_file, server_file)
    (cache_path / SCRCPY_SERVER_VERSION_FILENAME).write_text(
        f"{version}\n", encoding="utf-8"
    )
    logger.debug(f"Downloaded scrcpy-server {version} to {server_file}")
    return str(server_file)


# ---------------------------------------------------------------------------
# ADB backend
# ---------------------------------------------------------------------------

class AdbCommandBackend:
    """Concrete ADB backend used by :class:`ScrcpyScreenshotManager`.

    Mirrors the capabilities upstream needs from the yume-chan transport:
    ``push``, a raw shell, forward-tunnel management, server launch and a
    ``screencap`` fallback.
    """

    def __init__(
        self,
        device_id: str,
        adb_path: Optional[str] = None,
        host: str = "127.0.0.1",
    ) -> None:
        self.device_id = device_id
        self.adb_path = adb_path
        self.host = host

    async def _run(
        self,
        args: List[str],
        *,
        capture_output: bool = True,
        timeout: float = 30,
    ):
        return await run_adb_command(
            ["-s", self.device_id, *args],
            capture_output=capture_output,
            timeout=timeout,
            adb_path=self.adb_path,
        )

    async def push(self, local_path: str, remote_path: str) -> None:
        result = await self._run(
            ["push", local_path, remote_path], timeout=120
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Failed to push scrcpy-server to {remote_path}: {stderr.strip()}"
            )

    async def shell_text(self, args: List[str], timeout: float = 30) -> str:
        result = await self._run(["shell", *args], timeout=timeout)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"ADB shell command failed (exit {result.returncode}): "
                f"{stderr.strip() or ' '.join(args)}"
            )
        return (result.stdout or b"").decode("utf-8", errors="replace")

    async def forward_tcp(self, remote_socket: str) -> int:
        result = await self._run(
            ["forward", "tcp:0", f"localabstract:{remote_socket}"]
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Failed to create scrcpy forward tunnel: {stderr.strip()}"
            )
        text = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        for token in reversed(text.splitlines()):
            token = token.strip()
            if token.isdigit():
                return int(token)
        raise RuntimeError(
            f"ADB did not report a local port for the scrcpy tunnel: {text!r}"
        )

    async def remove_forward(self, local_port: int) -> None:
        with contextlib.suppress(Exception):
            await self._run(
                ["forward", "--remove", f"tcp:{local_port}"], timeout=10
            )

    async def start_server(self, args: List[str]) -> Any:
        executable = resolve_adb_executable(self.adb_path)
        return await asyncio.create_subprocess_exec(
            executable,
            "-s",
            self.device_id,
            "shell",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def screencap_png(self) -> bytes:
        result = await self._run(["shell", "screencap", "-p"])
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"ADB screencap failed: {stderr.strip()}")
        return result.stdout or b""

    async def screen_size(self) -> Dict[str, int]:
        output = await self.shell_text(["wm", "size"])
        match = re.search(r"(\d+)x(\d+)", output)
        if not match:
            raise RuntimeError(f"Unable to parse screen size: {output!r}")
        return {"width": int(match.group(1)), "height": int(match.group(2))}

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ScrcpyScreenshotManager:
    """Owns one scrcpy server connection and its latest decoded frame."""

    def __init__(
        self,
        adb: Any,
        push_server: Optional[Callable[[str, str], Any]] = None,
        options: Any = None,
        *,
        server_path: Optional[str] = None,
        host: str = "127.0.0.1",
        connection_factory: Optional[
            Callable[[str, int], Awaitable[Tuple[Any, Any]]]
        ] = None,
    ) -> None:
        self._adb = adb
        self._push_server = push_server
        self._host = host
        self._connection_factory = connection_factory or asyncio.open_connection
        self._server_path = server_path

        requested_bit_rate = int(
            _option(
                options,
                "video_bit_rate",
                "videoBitRate",
                default=DEFAULT_VIDEO_BIT_RATE,
            )
        )
        clamped_bit_rate = min(requested_bit_rate, MAX_VIDEO_BIT_RATE)
        if requested_bit_rate > MAX_VIDEO_BIT_RATE:
            logger.warning(
                f"videoBitRate {requested_bit_rate} exceeds maximum "
                f"{MAX_VIDEO_BIT_RATE}, clamped to {clamped_bit_rate}"
            )

        self.options = ResolvedScrcpyOptions(
            frame_rate=resolve_scrcpy_frame_rate(
                _option(options, "frame_rate", "frameRate", default=None)
            ),
            max_size=int(
                _option(options, "max_size", "maxSize", default=DEFAULT_MAX_SIZE)
            ),
            video_bit_rate=clamped_bit_rate,
            idle_timeout_ms=int(
                _option(
                    options,
                    "idle_timeout_ms",
                    "idleTimeoutMs",
                    default=DEFAULT_IDLE_TIMEOUT_MS,
                )
            ),
            video_reset_frame_timeout_ms=int(
                _option(
                    options,
                    "video_reset_frame_timeout_ms",
                    "videoResetFrameTimeoutMs",
                    default=DEFAULT_VIDEO_RESET_FRAME_TIMEOUT_MS,
                )
            ),
        )

        self._reader: Any = None
        self._writer: Any = None
        self._server_process: Any = None
        self._server_output_task: Optional[asyncio.Task] = None
        self._server_output_lines: List[str] = []
        self._consumer_task: Optional[asyncio.Task] = None
        self._local_port: Optional[int] = None
        self._scid: Optional[int] = None
        self._controller: Any = None

        self._sps_header: Optional[bytes] = None
        self._idle_handle: Any = None
        self._connection_task: Optional[asyncio.Task] = None
        self._dispose_task: Optional[asyncio.Task] = None
        self._disposed = False
        self._initialized = False
        self._ffmpeg_available: Optional[bool] = None

        self._keyframe_waiters: List[asyncio.Future] = []
        self._keyframe_listeners: Set[Callable[[RawKeyframe], Any]] = set()

        self._last_raw_keyframe: Optional[bytes] = None
        self._last_raw_keyframe_at = 0.0
        self._last_raw_keyframe_pts_us: Optional[int] = None
        self._last_raw_keyframe_estimated_age_ms: Optional[float] = None
        self._last_raw_keyframe_stream_epoch: Any = None
        self._stream_epoch: Any = object()
        self._stream_reader_epoch = 0
        self._video_resolution: Optional[Dict[str, int]] = None

        self._frame_freshness_barrier_pts_us: Optional[int] = None
        self._frame_freshness_barrier_reason: Optional[str] = None
        self._stream_startup_window: Optional[Dict[str, float]] = None
        self._frame_freshness_barrier_pending = False
        self._frame_freshness_barrier_generation = 0
        self._device_clock_calibration: Optional[DeviceClockCalibration] = None
        self._device_clock_calibration_task: Optional[asyncio.Task] = None
        self._has_retried_uncertain_clock_calibration = False
        self._last_frame_pts_us: Optional[int] = None
        self._frame_freshness_error: Optional[BaseException] = None
        self._last_frame_freshness_warning_at = 0.0
        self._has_established_video_frame = False
        self._video_reset_state: Optional[Dict[str, Any]] = None

    # -- environment ------------------------------------------------------

    async def init(self) -> None:
        """Validate prerequisites before any capture (ffmpeg + server jar)."""
        await self.validate_environment()

    async def validate_environment(self) -> None:
        """Validate environment prerequisites (ffmpeg, scrcpy-server)."""
        await self._ensure_ffmpeg_available()
        self.resolve_server_bin_path()

    def get_ffmpeg_path(self) -> str:
        """ffmpeg executable (explicit env override > system PATH)."""
        return os.environ.get("MIDSCENE_FFMPEG_PATH") or "ffmpeg"

    async def check_ffmpeg_available(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                self.get_ffmpeg_path(),
                "-version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await asyncio.wait_for(process.wait(), timeout=10)
            logger.debug(
                f"ffmpeg is available at: {self.get_ffmpeg_path()}"
            )
            return return_code == 0
        except Exception as error:  # noqa: BLE001 - reported as unavailable
            logger.debug(f"ffmpeg is not available: {error}")
            return False

    async def _ensure_ffmpeg_available(self) -> None:
        if self._ffmpeg_available is not None:
            return

        try:
            self._ffmpeg_available = await self.check_ffmpeg_available()
        except Exception as error:  # noqa: BLE001 - reported as unavailable
            self._ffmpeg_available = False
            logger.debug(f"Error checking ffmpeg availability: {error}")

        if not self._ffmpeg_available:
            logger.debug(
                "Warning: ffmpeg is not available. Scrcpy screenshot will be "
                "disabled. Install system ffmpeg: https://ffmpeg.org"
            )
            raise RuntimeError(
                "ffmpeg is not available, please use standard ADB screenshot mode"
            )

    def resolve_server_bin_path(self) -> str:
        """Resolve (or download) the local scrcpy-server jar path."""
        resolved = ensure_scrcpy_server(explicit_path=self._server_path)
        self._server_path = resolved
        return resolved

    # -- connection lifecycle --------------------------------------------

    async def _call_adb(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self._adb, method_name, None)
        if method is None:
            raise RuntimeError(
                f"Scrcpy ADB backend does not support {method_name}"
            )
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _push_server_file(self, local_path: str, remote_path: str) -> None:
        if self._push_server is not None:
            result = self._push_server(local_path, remote_path)
            if inspect.isawaitable(result):
                await result
            return
        await self._call_adb("push", local_path, remote_path)

    async def ensure_connected(self) -> None:
        if self._disposed:
            raise RuntimeError("Scrcpy manager has been disposed")

        if self._writer is not None and self._reader is not None:
            logger.debug("Scrcpy already connected")
            await self.ensure_frame_clock_calibration()
            self._reset_idle_timer()
            return

        if self._connection_task is not None:
            logger.debug(
                "Connection already in progress, sharing the same attempt..."
            )
            await asyncio.shield(self._connection_task)
            return

        task = asyncio.ensure_future(self._connect_scrcpy())
        self._connection_task = task
        try:
            await asyncio.shield(task)
        finally:
            if self._connection_task is task and task.done():
                self._connection_task = None

    def create_scrcpy_options(self) -> Dict[str, Any]:
        """Build the scrcpy server option set (upstream createScrcpyOptions)."""
        codec_options = [
            "i-frame-interval=0",
            "bitrate-mode=2",
            "repeat-previous-frame-after=0",
        ]
        if self.options.frame_rate is not None:
            codec_options.append(f"frame-rate={self.options.frame_rate}")

        scid = uuid.uuid4().int & 0x7FFFFFFF
        return {
            "audio": False,
            "control": True,
            "power_on": False,
            "clipboard_autosync": False,
            "tunnel_forward": True,
            "scid": scid,
            "max_size": self.options.max_size,
            "video_bit_rate": self.options.video_bit_rate,
            "max_fps": 10,
            "send_frame_meta": True,
            "video_codec_options": ",".join(codec_options),
        }

    @staticmethod
    def _build_server_args(server_options: Mapping[str, Any]) -> List[str]:
        def serialize(value: Any) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        ordered_keys = [
            "audio",
            "control",
            "power_on",
            "clipboard_autosync",
            "tunnel_forward",
            "scid",
            "max_size",
            "video_bit_rate",
            "max_fps",
            "send_frame_meta",
            "video_codec_options",
            "log_level",
        ]
        args = [
            f"CLASSPATH={DEFAULT_SERVER_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_PROTOCOL_VERSION,
        ]
        values = dict(server_options)
        values.setdefault("log_level", "info")
        for key in ordered_keys:
            if key not in values:
                continue
            value = values[key]
            if key == "scid" and isinstance(value, int):
                value = f"{value:08x}"
            args.append(f"{key}={serialize(value)}")
        return args

    async def _connect_scrcpy(self) -> None:
        server_output: List[str] = []
        server_output_task: Optional[asyncio.Task] = None

        try:
            logger.debug("Starting scrcpy connection...")

            server_bin_path = self.resolve_server_bin_path()
            await self._push_server_file(server_bin_path, DEFAULT_SERVER_PATH)

            server_options = self.create_scrcpy_options()
            self._scid = int(server_options["scid"])
            socket_name = f"scrcpy_{self._scid:08x}"

            # Calibrate immediately before starting the encoder so the first
            # packet can be validated without an extra ADB round trip.
            await self.ensure_frame_clock_calibration()

            # tunnel_forward means the device server listens on the abstract
            # socket, so start it before dialing the forwarded port.
            server_args = self._build_server_args(server_options)
            self._server_process = await self._call_adb(
                "start_server", server_args
            )
            server_output_task = asyncio.ensure_future(
                self._collect_server_output(self._server_process, server_output)
            )
            self._server_output_task = server_output_task

            self._local_port = int(
                await self._call_adb("forward_tcp", socket_name)
            )
            reader, writer = await self._open_video_connection(
                self._local_port
            )
            self._reader = reader
            self._writer = writer

            width, height = await self._read_video_header(reader)
            self._video_resolution = {"width": width, "height": height}
            logger.debug(f"Video stream started: {width}x{height}")

            self._advance_stream_epoch()
            self._stream_reader_epoch += 1
            self._stream_startup_window = {
                "deadline_at": _now_ms() + MAX_KEYFRAME_WAIT_MS
            }
            self._start_frame_consumer()
            self._reset_idle_timer()
            self._initialized = True

            logger.debug("Scrcpy connection established")
        except Exception as error:  # noqa: BLE001 - re-raised with diagnostics
            logger.debug(f"Failed to connect scrcpy: {error}")
            await self.disconnect()
            if server_output_task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        asyncio.shield(server_output_task),
                        SERVER_OUTPUT_DRAIN_TIMEOUT_MS / 1000,
                    )
            raise self._create_connection_error(error, server_output) from error

    async def _open_video_connection(self, local_port: int) -> Tuple[Any, Any]:
        """Dial the forwarded scrcpy video socket, tolerating server startup."""
        last_error: Optional[BaseException] = None
        for attempt in range(20):
            try:
                return await self._connection_factory(self._host, local_port)
            except (ConnectionError, OSError) as error:
                last_error = error
                if attempt == 19:
                    break
                await asyncio.sleep(0.1)
        assert last_error is not None
        raise last_error

    async def _read_video_header(self, reader: Any) -> Tuple[int, int]:
        # scrcpy 2.x/3.x: 64-byte device name, 4-byte codec fourcc, u32 width,
        # u32 height.  Legacy 1.x: 64-byte name then u16 width/height.
        await _read_exactly(reader, 64)
        first_four = await _read_exactly(reader, 4)
        if first_four in _CODEC_IDS:
            width = struct.unpack(">I", await _read_exactly(reader, 4))[0]
            height = struct.unpack(">I", await _read_exactly(reader, 4))[0]
        else:
            width, height = struct.unpack(">HH", first_four)
        if width <= 0 or height <= 0:
            raise RuntimeError(
                f"Scrcpy video stream reported an invalid size: "
                f"{width}x{height}"
            )
        return width, height

    async def _collect_server_output(
        self, process: Any, lines: List[str]
    ) -> None:
        if process is None:
            return
        tasks = []
        for stream in (
            getattr(process, "stdout", None),
            getattr(process, "stderr", None),
        ):
            if stream is not None:
                tasks.append(self._pump_server_stream(stream, lines))
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _pump_server_stream(self, stream: Any, lines: List[str]) -> None:
        try:
            while True:
                try:
                    chunk = await stream.readline()
                except (ValueError, RuntimeError):
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                if text:
                    logger.debug(f"Scrcpy server: {text}")
                lines.append(text)
                if len(lines) > MAX_SERVER_OUTPUT_LINES:
                    del lines[: len(lines) - MAX_SERVER_OUTPUT_LINES]
        except Exception as error:  # noqa: BLE001 - diagnostics only
            logger.debug(f"Failed to read scrcpy server output: {error}")

    def _create_connection_error(
        self, error: BaseException, server_output: List[str]
    ) -> RuntimeError:
        error_output = getattr(error, "output", None)
        if isinstance(error_output, (list, tuple)):
            error_output = [
                line for line in error_output if isinstance(line, str)
            ]
        else:
            error_output = []

        output: List[str] = []
        for line in [*error_output, *server_output]:
            if isinstance(line, str) and line.strip() and line not in output:
                output.append(line)

        message = str(error)
        output_details = (
            "\nScrcpy server output:\n" + "\n".join(output) if output else ""
        )
        return RuntimeError(
            f"Failed to connect scrcpy: {message}{output_details}"
        )

    def _start_frame_consumer(self) -> None:
        if self._reader is None:
            return
        reader = self._reader
        self._consumer_task = asyncio.ensure_future(
            self._consume_frames_loop(reader, self._stream_reader_epoch)
        )

    async def _consume_frames_loop(
        self, reader: Any, stream_reader_epoch: Optional[int] = None
    ) -> None:
        if stream_reader_epoch is None:
            stream_reader_epoch = self._stream_reader_epoch

        read_count = 0
        window_start = _now_ms()
        last_busy_warn = 0.0
        total_reads = 0
        end_reason = "stream closed"

        try:
            while True:
                header = await _read_exactly(reader, 12)
                pts, size = struct.unpack(">QI", header)
                data = await _read_exactly(reader, size)

                total_reads += 1
                read_count += 1

                now = _now_ms()
                elapsed = now - window_start
                if elapsed >= BUSY_LOOP_WINDOW_MS:
                    reads_per_sec = (read_count / elapsed) * 1000
                    if read_count > BUSY_LOOP_MAX_READS:
                        if now - last_busy_warn >= BUSY_LOOP_WARN_INTERVAL_MS:
                            logger.warning(
                                "[CPU-DIAG] Possible busy loop detected! "
                                f"{read_count} reads in {elapsed:.0f}ms "
                                f"({reads_per_sec:.0f} reads/sec). Total reads: "
                                f"{total_reads}. Throttling with "
                                f"{BUSY_LOOP_COOLDOWN_MS}ms delay."
                            )
                            last_busy_warn = now
                        await asyncio.sleep(BUSY_LOOP_COOLDOWN_MS / 1000)
                    else:
                        logger.debug(
                            "[CPU-DIAG] Frame loop stats: "
                            f"{read_count} reads in {elapsed:.0f}ms "
                            f"({reads_per_sec:.1f} reads/sec), total: "
                            f"{total_reads}"
                        )
                    read_count = 0
                    window_start = _now_ms()

                packet_pts = None if pts == _FRAME_CONFIG_PTS else pts
                self._process_packet(
                    data, packet_pts, stream_reader_epoch
                )
        except asyncio.IncompleteReadError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - stream teardown
            end_reason = "stream error"
            logger.debug(
                f"Frame consumer error (total reads: {total_reads}): {error}"
            )

        if self._reader is reader:
            await self.disconnect()
        logger.debug(
            f"Frame consumer loop ended ({end_reason}, total reads: "
            f"{total_reads})"
        )

    def _process_packet(
        self,
        data: bytes,
        pts: Optional[int],
        stream_reader_epoch: Optional[int] = None,
    ) -> None:
        """Process one framed scrcpy packet (upstream ``processFrame``)."""
        if stream_reader_epoch is None:
            stream_reader_epoch = self._stream_reader_epoch
        if stream_reader_epoch != self._stream_reader_epoch:
            return

        if pts is None:
            self._sps_header = bytes(data)
            logger.debug(
                "Received SPS/PPS configuration: "
                f"{len(self._sps_header)}B"
            )
            return

        active_reset = self._video_reset_state
        if active_reset is not None:
            active_reset["data_packets_seen"] += 1

        received_at_us = self._monotonic_time_us()
        if not self._is_frame_fresh(pts):
            return

        frame_buffer = bytes(data)
        is_key_frame = detect_h264_keyframe(frame_buffer)

        if is_key_frame and self._sps_header:
            captured_at, estimated_age_ms = self._estimate_frame_timing(
                pts, received_at_us
            )
            self._last_raw_keyframe = frame_buffer
            self._last_raw_keyframe_at = captured_at
            self._last_raw_keyframe_pts_us = pts
            self._last_raw_keyframe_estimated_age_ms = estimated_age_ms
            self._has_established_video_frame = True
            self._stream_startup_window = None

            frame = RawKeyframe(
                data=frame_buffer,
                header=self._sps_header,
                pts_us=pts,
                estimated_age_ms=estimated_age_ms,
                stream_epoch=self._stream_epoch,
                captured_at=captured_at,
            )
            self._last_raw_keyframe_stream_epoch = self._stream_epoch

            reset_state = self._video_reset_state
            if reset_state is not None:
                reset_state["frame_accepted"] = True
                if reset_state.get("write_task") is None:
                    self._video_reset_state = None

            if self._keyframe_waiters:
                self._notify_keyframe_waiters(frame)

            if self._keyframe_listeners and self._is_frame_age_acceptable(
                pts, received_at_us
            ):
                for listener in list(self._keyframe_listeners):
                    try:
                        listener(frame)
                    except Exception as error:  # noqa: BLE001
                        logger.debug(f"keyframe listener error: {error}")
                self._reset_idle_timer()

    # -- device clock calibration ----------------------------------------

    async def _read_device_clock_calibration(self) -> DeviceClockCalibration:
        started_at_us = self._monotonic_time_us()
        started_at_wall_ms = time.time() * 1000

        shell_text = getattr(self._adb, "shell_text", None)
        if shell_text is not None:
            output = shell_text(list(DEVICE_UPTIME_COMMAND))
            if inspect.isawaitable(output):
                output = await output
        else:
            device_id = getattr(self._adb, "device_id", None)
            if device_id is None:
                raise RuntimeError(
                    "Scrcpy ADB backend cannot read the device uptime clock"
                )
            result = await run_adb_command(
                ["-s", device_id, "shell", *DEVICE_UPTIME_COMMAND],
                capture_output=True,
                adb_path=getattr(self._adb, "adb_path", None),
            )
            if result.returncode != 0:
                stderr = (result.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                raise RuntimeError(
                    "Unable to read Android device uptime "
                    f"(exit {result.returncode}): {stderr.strip()}"
                )
            output = (result.stdout or b"").decode("utf-8", errors="replace")

        finished_at_us = self._monotonic_time_us()
        finished_at_wall_ms = time.time() * 1000
        return DeviceClockCalibration(
            device_uptime_us=parse_device_uptime_ms(output) * 1_000,
            host_monotonic_us=started_at_us
            + (finished_at_us - started_at_us) // 2,
            host_wall_time_ms=started_at_wall_ms
            + (finished_at_wall_ms - started_at_wall_ms) / 2,
            round_trip_us=finished_at_us - started_at_us,
        )

    async def _sample_frame_clock_calibration(self, force: bool) -> None:
        if not force and self._device_clock_calibration is not None:
            return
        if self._device_clock_calibration_task is not None:
            await asyncio.shield(self._device_clock_calibration_task)
            if self._device_clock_calibration is None:
                raise RuntimeError(
                    "Scrcpy stream epoch changed while calibrating the frame "
                    "clock"
                )
            return

        calibration_task = asyncio.ensure_future(
            self._read_device_clock_calibration()
        )
        self._device_clock_calibration_task = calibration_task
        try:
            sampled = await asyncio.shield(calibration_task)
            if self._device_clock_calibration_task is not calibration_task:
                raise RuntimeError(
                    "Scrcpy stream epoch changed while calibrating the frame "
                    "clock"
                )

            previous = self._device_clock_calibration
            calibration = sampled
            if (
                force
                and previous is not None
                and previous.round_trip_us <= sampled.round_trip_us
            ):
                calibration = previous

            self._device_clock_calibration = calibration
            if previous is None:
                self._frame_freshness_barrier_pending = False
                self._last_frame_pts_us = None
                self._frame_freshness_error = None
            logger.debug(
                "Calibrated scrcpy frame clock for stream epoch "
                f"(RTT={calibration.round_trip_us / 1000:.0f}ms)"
            )
        finally:
            if self._device_clock_calibration_task is calibration_task:
                self._device_clock_calibration_task = None

    async def ensure_frame_clock_calibration(self) -> None:
        await self._sample_frame_clock_calibration(False)

    async def _recalibrate_frame_clock(self) -> None:
        await self._sample_frame_clock_calibration(True)

    async def set_freshness_barrier(
        self,
        reason: str,
        options: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """Arm a PTS barrier projected onto the device clock (upstream)."""
        cached_frame = self._get_cached_keyframe_candidate()
        self._frame_freshness_barrier_generation += 1
        generation = self._frame_freshness_barrier_generation
        self._frame_freshness_barrier_pending = True
        self._clear_frame_cache()

        try:
            calibration = self._device_clock_calibration
            if calibration is None:
                raise RuntimeError(
                    "Scrcpy frame clock is not calibrated for the current "
                    "stream epoch"
                )

            host_monotonic_us = _option(
                options,
                "host_monotonic_us",
                "hostMonotonicUs",
                default=None,
            )
            if host_monotonic_us is None:
                host_monotonic_us = self._monotonic_time_us()

            estimated_device_now_us = self._estimate_device_time_us(
                int(host_monotonic_us), calibration
            )
            conservative_device_now_us = (
                estimated_device_now_us
                + self._get_calibration_uncertainty_us(calibration)
            )
            barrier_pts_us = (conservative_device_now_us // 1_000 + 1) * 1_000

            if generation != self._frame_freshness_barrier_generation:
                return (
                    self._frame_freshness_barrier_pts_us
                    if self._frame_freshness_barrier_pts_us is not None
                    else barrier_pts_us
                )

            current_barrier = self._frame_freshness_barrier_pts_us
            self._frame_freshness_barrier_pts_us = (
                barrier_pts_us
                if current_barrier is None or barrier_pts_us > current_barrier
                else current_barrier
            )
            self._frame_freshness_barrier_reason = reason
            self._frame_freshness_barrier_pending = False
            self._frame_freshness_error = None
            self._last_frame_pts_us = None

            if (
                cached_frame is not None
                and cached_frame.pts_us is not None
                and cached_frame.pts_us
                >= self._frame_freshness_barrier_pts_us
            ):
                self._restore_frame_cache(cached_frame)
                logger.debug(
                    f"Preserved cached frame PTS {cached_frame.pts_us}us "
                    f"because it crosses the newly armed {reason} barrier"
                )
            else:
                self._clear_frame_cache()

            logger.debug(
                "Armed frame freshness barrier at PTS "
                f"{self._frame_freshness_barrier_pts_us}us ({reason})"
            )
            return self._frame_freshness_barrier_pts_us
        except Exception as error:  # noqa: BLE001 - wrapped below
            if generation == self._frame_freshness_barrier_generation:
                self._frame_freshness_barrier_pending = False
                message = (
                    "Unable to establish scrcpy frame freshness barrier "
                    f"({reason}): {error}"
                )
                self._frame_freshness_error = RuntimeError(message)
                raise self._frame_freshness_error from error
            raise

    def _is_frame_fresh(self, packet_pts_us: Optional[int]) -> bool:
        if self._frame_freshness_barrier_pending:
            return False

        if packet_pts_us is not None:
            if (
                self._last_frame_pts_us is not None
                and packet_pts_us < self._last_frame_pts_us
            ):
                self._frame_freshness_error = RuntimeError(
                    "Scrcpy frame PTS moved backwards; refusing frames until "
                    "the device clock anchor is recalibrated"
                )
                self._frame_freshness_barrier_pending = True
                self._frame_freshness_barrier_pts_us = None
                self._frame_freshness_barrier_reason = None
                self._device_clock_calibration = None
                self._has_retried_uncertain_clock_calibration = False
                self._clear_frame_cache()
                self._warn_frame_freshness()
                return False
            self._last_frame_pts_us = packet_pts_us

        if self._frame_freshness_barrier_pts_us is None:
            return True

        if packet_pts_us is None:
            self._frame_freshness_error = RuntimeError(
                "Scrcpy frame has no PTS metadata; cannot prove that it is "
                "newer than the freshness barrier"
            )
            self._warn_frame_freshness()
            return False

        if packet_pts_us >= self._frame_freshness_barrier_pts_us:
            if self._frame_freshness_error is not None:
                logger.debug(
                    "Scrcpy video crossed the "
                    f"{self._frame_freshness_barrier_reason or 'active'} "
                    f"freshness barrier at PTS {packet_pts_us}us"
                )
            self._frame_freshness_error = None
            return True

        behind_barrier_us = (
            self._frame_freshness_barrier_pts_us - packet_pts_us
        )
        self._frame_freshness_error = RuntimeError(
            "Scrcpy frame predates the "
            f"{self._frame_freshness_barrier_reason or 'active'} freshness "
            f"barrier by {behind_barrier_us / 1000}ms; refusing to use it"
        )
        self._clear_frame_cache()
        logger.debug(str(self._frame_freshness_error))
        return False

    def _estimate_frame_age_us(
        self,
        packet_pts_us: Optional[int],
        host_monotonic_us: Optional[int] = None,
    ) -> Optional[int]:
        estimate = self._estimate_frame_age(
            packet_pts_us, host_monotonic_us
        )
        return None if estimate is None else estimate.estimated_age_us

    def _estimate_frame_age(
        self,
        packet_pts_us: Optional[int],
        host_monotonic_us: Optional[int] = None,
    ) -> Optional[FrameAgeEstimate]:
        calibration = self._device_clock_calibration
        if packet_pts_us is None or calibration is None:
            return None
        if host_monotonic_us is None:
            host_monotonic_us = self._monotonic_time_us()

        estimated_device_now_us = self._estimate_device_time_us(
            host_monotonic_us, calibration
        )
        estimated_age_us = (
            estimated_device_now_us - packet_pts_us
            if estimated_device_now_us > packet_pts_us
            else 0
        )
        uncertainty_us = self._get_calibration_uncertainty_us(calibration)
        return FrameAgeEstimate(
            estimated_age_us=estimated_age_us,
            calibration_uncertainty_us=uncertainty_us,
            upper_bound_us=estimated_age_us + uncertainty_us,
        )

    @staticmethod
    def _estimate_device_time_us(
        host_monotonic_us: int, calibration: DeviceClockCalibration
    ) -> int:
        return calibration.device_uptime_us + (
            host_monotonic_us - calibration.host_monotonic_us
        )

    @staticmethod
    def _get_calibration_uncertainty_us(
        calibration: DeviceClockCalibration,
    ) -> int:
        return (calibration.round_trip_us + 1) // 2

    def _is_frame_age_acceptable(
        self,
        packet_pts_us: Optional[int],
        host_monotonic_us: Optional[int] = None,
    ) -> bool:
        age = self._estimate_frame_age(packet_pts_us, host_monotonic_us)
        if age is None:
            if packet_pts_us is None:
                message = (
                    "Scrcpy frame has no PTS metadata; cannot prove its "
                    "absolute age"
                )
            else:
                message = (
                    "Scrcpy frame clock is not calibrated; cannot prove its "
                    "absolute age"
                )
            self._frame_freshness_error = RuntimeError(message)
            self._warn_frame_freshness()
            return False

        if age.upper_bound_us <= MAX_FRAME_AGE_US:
            if self._frame_freshness_error is not None:
                logger.debug(
                    "Scrcpy frame age recovered "
                    f"(upper bound={age.upper_bound_us / 1000}ms, "
                    f"estimated={age.estimated_age_us / 1000}ms, clock "
                    f"uncertainty<={age.calibration_uncertainty_us / 1000}ms)"
                )
                self._frame_freshness_error = None
            return True

        self._frame_freshness_error = RuntimeError(
            "Scrcpy frame absolute age upper bound is "
            f"{age.upper_bound_us / 1000}ms "
            f"(estimated={age.estimated_age_us / 1000}ms, clock "
            f"uncertainty<={age.calibration_uncertainty_us / 1000}ms), "
            f"exceeding the {MAX_FRAME_AGE_US / 1000}ms limit"
        )
        self._warn_frame_freshness()
        return False

    def _warn_frame_freshness(self) -> None:
        if self._frame_freshness_error is None:
            return
        now = _now_ms()
        if (
            now - self._last_frame_freshness_warning_at
            >= FRAME_FRESHNESS_WARN_INTERVAL_MS
        ):
            logger.warning(str(self._frame_freshness_error))
            self._last_frame_freshness_warning_at = now

    def _estimate_frame_timing(
        self, packet_pts_us: Optional[int], received_at_us: int
    ) -> Tuple[float, Optional[float]]:
        calibration = self._device_clock_calibration
        if packet_pts_us is None or calibration is None:
            return time.time() * 1000, None

        estimated_age_us = (
            self._estimate_frame_age_us(packet_pts_us, received_at_us) or 0
        )
        estimated_age_ms = estimated_age_us / 1000
        received_at_wall_time_ms = calibration.host_wall_time_ms + (
            received_at_us - calibration.host_monotonic_us
        ) / 1000
        return (
            received_at_wall_time_ms - estimated_age_ms,
            estimated_age_ms,
        )

    def _clear_frame_cache(self) -> None:
        self._last_raw_keyframe = None
        self._last_raw_keyframe_at = 0.0
        self._last_raw_keyframe_pts_us = None
        self._last_raw_keyframe_estimated_age_ms = None
        self._last_raw_keyframe_stream_epoch = None

    def _restore_frame_cache(self, frame: RawKeyframe) -> None:
        self._last_raw_keyframe = frame.data
        self._last_raw_keyframe_at = frame.captured_at
        self._last_raw_keyframe_pts_us = frame.pts_us
        self._last_raw_keyframe_estimated_age_ms = frame.estimated_age_ms
        self._last_raw_keyframe_stream_epoch = frame.stream_epoch

    def _monotonic_time_us(self) -> int:
        return time.monotonic_ns() // 1000

    def _advance_stream_epoch(self) -> None:
        self._stream_epoch = object()

    def _reset_frame_freshness_state(self) -> None:
        self._frame_freshness_barrier_pts_us = None
        self._frame_freshness_barrier_reason = None
        self._stream_startup_window = None
        self._frame_freshness_barrier_pending = False
        self._frame_freshness_barrier_generation = 0
        self._device_clock_calibration = None
        self._device_clock_calibration_task = None
        self._has_retried_uncertain_clock_calibration = False
        self._last_frame_pts_us = None
        self._frame_freshness_error = None
        self._last_frame_freshness_warning_at = 0.0
        self._has_established_video_frame = False
        self._video_reset_state = None

    # -- video reset ------------------------------------------------------

    async def _request_video_reset(
        self, deadline_at: Optional[float] = None
    ) -> Dict[str, Any]:
        if deadline_at is None:
            deadline_at = _now_ms() + FRESH_FRAME_TIMEOUT_MS

        active_reset = self._video_reset_state
        if active_reset is not None:
            write_task = active_reset.get("write_task")
            if write_task is not None:
                await self._wait_for_video_reset_write(
                    write_task, deadline_at
                )
            return active_reset

        controller = self._controller
        reset_video = getattr(controller, "reset_video", None)
        if reset_video is None:
            raise RuntimeError(
                "Scrcpy control channel is unavailable for video reset"
            )

        reset_state: Dict[str, Any] = {
            "previous_sps_header": self._sps_header,
            "write_task": None,
            "frame_accepted": False,
            "data_packets_seen": 0,
        }
        self._video_reset_state = reset_state

        self._advance_stream_epoch()
        self._clear_frame_cache()
        self._sps_header = None

        async def run_reset() -> None:
            try:
                result = reset_video()
                if inspect.isawaitable(result):
                    await result
            except BaseException:
                if self._video_reset_state is reset_state:
                    if self._sps_header is None:
                        self._sps_header = reset_state["previous_sps_header"]
                    self._video_reset_state = None
                raise
            else:
                logger.debug("Requested scrcpy in-band video reset")
                if self._video_reset_state is reset_state:
                    reset_state["write_task"] = None
                    if reset_state["frame_accepted"]:
                        self._video_reset_state = None

        reset_task = asyncio.ensure_future(run_reset())
        reset_state["write_task"] = reset_task

        # A caller may time out before the write settles; keep observing it so
        # a later rejection never becomes an unhandled task exception.
        def _consume_outcome(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            with contextlib.suppress(Exception):
                task.exception()

        reset_task.add_done_callback(_consume_outcome)
        await self._wait_for_video_reset_write(reset_task, deadline_at)
        return reset_state

    async def _wait_for_video_reset_write(
        self, write_task: asyncio.Task, deadline_at: float
    ) -> None:
        remaining_ms = deadline_at - _now_ms()
        if remaining_ms <= 0:
            raise RuntimeError(
                "Scrcpy video reset exceeded the freshness deadline"
            )
        try:
            await asyncio.wait_for(
                asyncio.shield(write_task), remaining_ms / 1000
            )
        except asyncio.TimeoutError as error:
            raise RuntimeError(
                "Scrcpy video reset exceeded the freshness deadline"
            ) from error

    def _create_video_reset_frame_timeout_error(
        self, video_reset: Mapping[str, Any]
    ) -> ScrcpyFrameWaitTimeoutError:
        timeout_ms = self.options.video_reset_frame_timeout_ms
        data_packets_seen = int(video_reset.get("data_packets_seen", 0))
        observation = (
            "no data packets were observed while reset recovery was active"
            if data_packets_seen == 0
            else f"{data_packets_seen} data packet"
            f"{' was' if data_packets_seen == 1 else 's were'} observed while "
            "reset recovery was active"
        )
        message = (
            "Scrcpy video reset produced no usable fresh keyframe within the "
            f"{timeout_ms}ms post-reset window; {observation}"
        )
        logger.debug(message)
        return ScrcpyFrameWaitTimeoutError(message, timeout_ms)

    async def _close_stale_stream_and_create_fallback_error(
        self, error: BaseException
    ) -> ScrcpyFreshFrameUnavailableError:
        if (
            self._stream_startup_window is not None
            and self._frame_freshness_barrier_pts_us is None
        ):
            failure_kind = "stream-startup"
        else:
            failure_kind = "freshness-target"

        if isinstance(error, ScrcpyFrameWaitTimeoutError):
            timeout_ms = error.timeout_ms
        elif failure_kind == "stream-startup":
            timeout_ms = MAX_KEYFRAME_WAIT_MS
        else:
            timeout_ms = FRESH_FRAME_TIMEOUT_MS

        await self.disconnect()
        return ScrcpyFreshFrameUnavailableError(
            "Unable to obtain a fresh scrcpy frame; the stale stream epoch "
            "was closed so the caller can restart it or use ADB screenshot "
            f"fallback. {error}",
            failure_kind=failure_kind,
            timeout_ms=timeout_ms,
            video_bit_rate=self.options.video_bit_rate,
            cause=error,
        )

    # -- capture ----------------------------------------------------------

    async def get_screenshot_jpeg(self) -> bytes:
        perf_start = _now_ms()

        connect_start = _now_ms()
        await self.ensure_connected()
        connect_time = _now_ms() - connect_start

        frame_start = _now_ms()
        try:
            await self.ensure_frame_clock_calibration()
            await self._wait_for_keyframe()
            frame = await self._wait_for_planning_frame()
        except Exception as error:  # noqa: BLE001 - wrapped as fallback error
            raise await self._close_stale_stream_and_create_fallback_error(
                error
            ) from error
        frame_wait_time = _now_ms() - frame_start
        keyframe_buffer = frame.header + frame.data

        self._reset_idle_timer()

        logger.debug(
            f"Decoding H.264 stream: {len(keyframe_buffer)} bytes "
            "(post-barrier)"
        )

        decode_start = _now_ms()
        result = await self._decode_h264_to_jpeg(keyframe_buffer)
        decode_time = _now_ms() - decode_start
        self._record_decoded_frame(frame, result)

        logger.debug(
            f"Performance: total={_now_ms() - perf_start:.0f}ms "
            f"(connect={connect_time:.0f}ms, "
            f"frameWait={frame_wait_time:.0f}ms, "
            f"decode={decode_time:.0f}ms)"
        )
        return result

    async def screenshot(self) -> str:
        """Capture a JPEG and return it as a raw base64 string."""
        jpeg = await self.get_screenshot_jpeg()
        return base64.b64encode(jpeg).decode("ascii")

    def get_resolution(self) -> Optional[Dict[str, int]]:
        if self._video_resolution is None:
            return None
        return dict(self._video_resolution)

    async def size(self) -> Optional[Dict[str, int]]:
        return self.get_resolution()

    def _notify_keyframe_waiters(self, frame: RawKeyframe) -> None:
        waiters = self._keyframe_waiters
        self._keyframe_waiters = []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(frame)

    async def _wait_for_next_keyframe(self, timeout_ms: float) -> RawKeyframe:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future = loop.create_future()
        self._keyframe_waiters.append(waiter)
        try:
            return await asyncio.wait_for(waiter, timeout_ms / 1000)
        except asyncio.TimeoutError as error:
            if waiter in self._keyframe_waiters:
                self._keyframe_waiters.remove(waiter)
            raise RuntimeError(
                f"No fresh keyframe received within {timeout_ms}ms"
            ) from error

    async def _wait_for_keyframe(self) -> None:
        start_time = _now_ms()

        while (
            not self._sps_header
            and _now_ms() - start_time < MAX_KEYFRAME_WAIT_MS
        ):
            elapsed = _now_ms() - start_time
            logger.debug(
                f"Waiting for first keyframe (SPS/PPS header)... {elapsed:.0f}ms"
            )
            await asyncio.sleep(KEYFRAME_POLL_INTERVAL_MS / 1000)

        if not self._sps_header:
            raise RuntimeError(
                f"No keyframe received within {MAX_KEYFRAME_WAIT_MS}ms. "
                "Device may have a long GOP interval or video encoding "
                "issues. Please retry."
            )

    async def _is_planning_candidate_fresh_enough(
        self, candidate: RawKeyframe
    ) -> bool:
        if candidate.pts_us is None:
            raise RuntimeError(
                "Scrcpy frame has no PTS metadata; cannot prove planning "
                "freshness"
            )

        age = self._estimate_frame_age(
            candidate.pts_us, self._monotonic_time_us()
        )
        if age is None:
            raise RuntimeError(
                "Scrcpy frame clock is not calibrated; cannot prove planning "
                "freshness"
            )

        if age.upper_bound_us <= MAX_FRAME_AGE_US:
            return True

        uncertainty_only_exceeded_limit = (
            age.estimated_age_us <= MAX_FRAME_AGE_US
            and age.upper_bound_us > MAX_FRAME_AGE_US
        )
        if uncertainty_only_exceeded_limit:
            if not self._has_retried_uncertain_clock_calibration:
                self._has_retried_uncertain_clock_calibration = True
                logger.debug(
                    f"Planning candidate PTS {candidate.pts_us}us exceeded "
                    f"the {MAX_FRAME_AGE_US / 1000}ms upper-bound limit only "
                    "because clock uncertainty was "
                    f"{age.calibration_uncertainty_us / 1000}ms; "
                    "recalibrating once before deciding freshness"
                )
                try:
                    await self._recalibrate_frame_clock()
                except Exception as error:  # noqa: BLE001 - best effort
                    logger.debug(
                        "Unable to recalibrate scrcpy frame clock after an "
                        f"uncertainty-only freshness result: {error}"
                    )
                if (
                    candidate.stream_epoch is not None
                    and candidate.stream_epoch is not self._stream_epoch
                ):
                    raise RuntimeError(
                        "Scrcpy stream epoch changed while recalibrating "
                        "planning frame freshness"
                    )

                recalibrated_age = self._estimate_frame_age(
                    candidate.pts_us, self._monotonic_time_us()
                )
                if recalibrated_age is None:
                    raise RuntimeError(
                        "Scrcpy frame clock is not calibrated; cannot prove "
                        "planning freshness"
                    )
                age = recalibrated_age
                if age.upper_bound_us <= MAX_FRAME_AGE_US:
                    logger.debug(
                        f"Planning candidate PTS {candidate.pts_us}us accepted "
                        "after clock recalibration "
                        f"(estimated={age.estimated_age_us / 1000}ms, "
                        "uncertainty<="
                        f"{age.calibration_uncertainty_us / 1000}ms)"
                    )
                    return True

            if age.estimated_age_us <= MAX_FRAME_AGE_US:
                logger.debug(
                    f"Planning candidate PTS {candidate.pts_us}us remains "
                    "uncertainty-only after the calibration retry; accepting "
                    f"estimated age {age.estimated_age_us / 1000}ms despite "
                    "clock uncertainty<="
                    f"{age.calibration_uncertainty_us / 1000}ms"
                )
                return True

        logger.debug(
            f"Planning candidate PTS {candidate.pts_us}us has absolute age "
            f"upper bound {age.upper_bound_us / 1000}ms "
            f"(estimated={age.estimated_age_us / 1000}ms, clock "
            f"uncertainty<={age.calibration_uncertainty_us / 1000}ms), "
            f"exceeding the {MAX_FRAME_AGE_US / 1000}ms limit; arming a "
            "planning freshness barrier"
        )
        return False

    async def _wait_for_planning_frame(self) -> RawKeyframe:
        planning_barrier_armed = False
        video_reset_attempted = False
        video_reset: Optional[Dict[str, Any]] = None
        planning_started_at = _now_ms()

        startup_window_remaining_ms = 0.0
        if self._stream_startup_window is not None:
            startup_window_remaining_ms = (
                self._stream_startup_window["deadline_at"]
                - planning_started_at
            )
            if startup_window_remaining_ms <= 0:
                self._stream_startup_window = None

        deadline = planning_started_at + (
            startup_window_remaining_ms
            if startup_window_remaining_ms > 0
            else FRESH_FRAME_TIMEOUT_MS
        )
        candidate = self._get_cached_keyframe_candidate()

        while True:
            if candidate is not None:
                if await self._is_planning_candidate_fresh_enough(candidate):
                    return candidate

                if not planning_barrier_armed:
                    await self.set_freshness_barrier("stale planning frame")
                    planning_barrier_armed = True
                    deadline = _now_ms() + FRESH_FRAME_TIMEOUT_MS
                else:
                    self._clear_frame_cache()

            remaining_ms = deadline - _now_ms()
            if remaining_ms <= 0:
                if video_reset is not None:
                    raise self._create_video_reset_frame_timeout_error(
                        video_reset
                    )
                raise RuntimeError(
                    "No scrcpy frame crossed the active freshness target "
                    f"within {FRESH_FRAME_TIMEOUT_MS}ms"
                )

            should_try_video_reset = (
                not video_reset_attempted
                and self._has_established_video_frame
                and self._stream_startup_window is None
                and getattr(self._controller, "reset_video", None) is not None
                and remaining_ms > VIDEO_RESET_DELAY_MS
            )
            next_frame_wait_ms = (
                VIDEO_RESET_DELAY_MS
                if should_try_video_reset
                else remaining_ms
            )

            try:
                candidate = await self._wait_for_next_keyframe(
                    next_frame_wait_ms
                )
            except Exception as error:  # noqa: BLE001 - deadline handling
                if not should_try_video_reset:
                    if video_reset is not None:
                        raise self._create_video_reset_frame_timeout_error(
                            video_reset
                        ) from error
                    raise
                video_reset_attempted = True
                try:
                    video_reset = await self._request_video_reset(deadline)
                    deadline = (
                        _now_ms() + self.options.video_reset_frame_timeout_ms
                    )
                    logger.debug(
                        "Scrcpy video reset control write completed; waiting "
                        f"up to {self.options.video_reset_frame_timeout_ms}ms "
                        "for a post-reset frame"
                    )
                except Exception as reset_error:  # noqa: BLE001
                    logger.debug(
                        f"Unable to request scrcpy video reset: {reset_error}"
                    )
                candidate = self._get_cached_keyframe_candidate()

    def _get_cached_keyframe_candidate(self) -> Optional[RawKeyframe]:
        if self._last_raw_keyframe is None or not self._sps_header:
            return None
        return RawKeyframe(
            data=self._last_raw_keyframe,
            header=self._sps_header,
            pts_us=self._last_raw_keyframe_pts_us,
            estimated_age_ms=self._last_raw_keyframe_estimated_age_ms,
            stream_epoch=self._last_raw_keyframe_stream_epoch,
            captured_at=self._last_raw_keyframe_at,
        )

    def get_latest_raw_keyframe(self) -> Optional[RawKeyframe]:
        frame = self._get_cached_keyframe_candidate()
        if frame is None or not self._is_frame_age_acceptable(frame.pts_us):
            return None
        return frame

    def subscribe_keyframes(
        self, listener: Callable[[RawKeyframe], Any]
    ) -> Callable[[], None]:
        self._keyframe_listeners.add(listener)
        self._reset_idle_timer()

        def unsubscribe() -> None:
            self._keyframe_listeners.discard(listener)
            self._reset_idle_timer()

        return unsubscribe

    async def decode_raw_keyframe_to_jpeg(self, frame: RawKeyframe) -> bytes:
        result = await self._decode_h264_to_jpeg(frame.header + frame.data)
        self._record_decoded_frame(frame, result)
        return result

    def _record_decoded_frame(self, frame: RawKeyframe, jpeg: bytes) -> None:
        if frame.stream_epoch is not self._stream_epoch:
            return

        decoded_resolution = encoded_image_info_of_buffer(jpeg)
        if self._video_resolution != decoded_resolution:
            logger.debug(
                "Updating scrcpy resolution from "
                f"{self._video_resolution} to decoded frame "
                f"{decoded_resolution}"
            )
            self._video_resolution = decoded_resolution
        self._has_established_video_frame = True
        self._stream_startup_window = None

    async def _decode_h264_to_jpeg(self, h264_buffer: bytes) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                self.get_ffmpeg_path(),
                *_FFMPEG_ARGS,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as error:  # noqa: BLE001 - reported to caller
            raise RuntimeError(
                f"Failed to spawn ffmpeg process: {error}"
            ) from error

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(h264_buffer), timeout=30
            )
        except asyncio.TimeoutError as error:
            with contextlib.suppress(Exception):
                process.kill()
            await process.wait()
            raise RuntimeError(
                "H.264 to JPEG decode failed: ffmpeg timed out"
            ) from error

        if process.returncode == 0 and stdout:
            logger.debug(
                f"FFmpeg decode successful, JPEG size: {len(stdout)} bytes"
            )
            return stdout

        error_message = (
            stderr.decode("utf-8", errors="replace").strip()
            or f"FFmpeg exited with code {process.returncode}"
        )
        logger.debug(f"FFmpeg decode failed: {error_message}")
        raise RuntimeError(f"H.264 to JPEG decode failed: {error_message}")

    # -- idle / teardown --------------------------------------------------

    def _reset_idle_timer(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

        if not self.options.idle_timeout_ms:
            return
        if self._keyframe_listeners:
            return

        loop = asyncio.get_running_loop()

        def on_idle() -> None:
            logger.debug("Idle timeout reached, disconnecting scrcpy")
            asyncio.ensure_future(self.disconnect())

        self._idle_handle = loop.call_later(
            self.options.idle_timeout_ms / 1000, on_idle
        )

    def is_connected(self) -> bool:
        return self._initialized and self._writer is not None

    async def disconnect(self) -> None:
        logger.debug("Disconnecting scrcpy...")

        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

        client = self._writer
        process = self._server_process
        output_task = self._server_output_task
        consumer_task = self._consumer_task
        local_port = self._local_port

        self._writer = None
        self._reader = None
        self._server_process = None
        self._server_output_task = None
        self._consumer_task = None
        self._local_port = None
        self._sps_header = None
        self._clear_frame_cache()
        self._initialized = False
        self._keyframe_waiters = []
        self._keyframe_listeners.clear()
        self._reset_frame_freshness_state()
        self._advance_stream_epoch()
        self._stream_reader_epoch += 1

        current_task = asyncio.current_task()
        if (
            consumer_task is not None
            and consumer_task is not current_task
            and not consumer_task.done()
        ):
            consumer_task.cancel()
            with contextlib.suppress(BaseException):
                await consumer_task

        if output_task is not None and output_task is not current_task:
            output_task.cancel()
            with contextlib.suppress(BaseException):
                await output_task

        if client is not None:
            with contextlib.suppress(Exception):
                close_result = client.close()
                if inspect.isawaitable(close_result):
                    await close_result
            wait_closed = getattr(client, "wait_closed", None)
            if wait_closed is not None:
                with contextlib.suppress(Exception):
                    await wait_closed()

        if process is not None:
            with contextlib.suppress(Exception):
                terminate = getattr(process, "terminate", None)
                if terminate is not None:
                    terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2)
            with contextlib.suppress(Exception):
                if getattr(process, "returncode", None) is None:
                    process.kill()
                    await process.wait()

        if local_port is not None:
            with contextlib.suppress(Exception):
                await self._call_adb("remove_forward", local_port)

        logger.debug("Scrcpy disconnected")

    async def stop(self) -> None:
        """Stop the current stream (alias of :meth:`disconnect`)."""
        await self.disconnect()

    async def dispose(self) -> None:
        """Permanently release the stream and any owned ADB transport."""
        if self._dispose_task is not None:
            await asyncio.shield(self._dispose_task)
            return

        self._disposed = True

        async def _dispose() -> None:
            if self._connection_task is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self._connection_task)
            await self.disconnect()
            close = getattr(self._adb, "close", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result

        task = asyncio.ensure_future(_dispose())
        self._dispose_task = task
        await asyncio.shield(task)

    async def close(self) -> None:
        """Permanently release the manager (alias of :meth:`dispose`)."""
        await self.dispose()


async def _read_exactly(reader: Any, size: int) -> bytes:
    """Read exactly ``size`` bytes from a StreamReader-like object."""
    if size < 0:
        raise RuntimeError(f"Invalid scrcpy packet size: {size}")
    if size == 0:
        return b""
    return await reader.readexactly(size)


__all__ = [
    "AdbCommandBackend",
    "DEFAULT_MAX_SIZE",
    "DEFAULT_SCRCPY_CONFIG",
    "DEFAULT_VIDEO_BIT_RATE",
    "DEFAULT_VIDEO_RESET_FRAME_TIMEOUT_MS",
    "DEFAULT_IDLE_TIMEOUT_MS",
    "DEFAULT_SERVER_PATH",
    "FRESH_FRAME_TIMEOUT_MS",
    "MAX_FRAME_AGE_US",
    "MAX_KEYFRAME_WAIT_MS",
    "MAX_SCAN_BYTES",
    "MAX_VIDEO_BIT_RATE",
    "NAL_TYPE_IDR",
    "NAL_TYPE_MASK",
    "NAL_TYPE_PPS",
    "NAL_TYPE_SPS",
    "RawKeyframe",
    "ResolvedScrcpyOptions",
    "SCRCPY_FRESH_FRAME_UNAVAILABLE_ERROR_CODE",
    "SCRCPY_PROTOCOL_VERSION",
    "SCRCPY_SERVER_VERSION_TAG",
    "ScrcpyConfig",
    "ScrcpyFreshFrameUnavailableError",
    "ScrcpyScreenshotManager",
    "ScrcpyStatus",
    "detect_h264_keyframe",
    "ensure_scrcpy_server",
    "get_scrcpy_server_download_url",
    "is_scrcpy_fresh_frame_unavailable_error",
    "parse_device_uptime_ms",
    "resolve_scrcpy_frame_rate",
    "should_download_scrcpy_server",
]
