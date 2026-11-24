"""WDA MJPEG frame source.

Synced from upstream packages/ios/src/mjpeg-frame-source.ts. Sampling the
latest decoded frame is near-instant compared to WDA's per-screenshot cost.
"""

import asyncio
import base64

import httpx
from loguru import logger

SOI_0 = 0xFF
SOI_1 = 0xD8
EOI_1 = 0xD9

_MAX_PENDING_BYTES = 8 * 1024 * 1024
_RECONNECT_DELAY_SECONDS = 0.5
_FIRST_FRAME_POLL_SECONDS = 0.03


def extract_jpeg_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Extract complete JPEG frames from a (possibly partial) MJPEG buffer.

    Anything before the first SOI marker is discarded; trailing incomplete
    bytes are returned as `rest`.
    """
    frames: list[bytes] = []
    search_start = 0
    length = len(buffer)

    while True:
        soi = -1
        for index in range(search_start, length - 1):
            if buffer[index] == SOI_0 and buffer[index + 1] == SOI_1:
                soi = index
                break
        if soi == -1:
            last = length - 1
            rest = (
                buffer[last:] if last >= search_start and buffer[last] == SOI_0 else b""
            )
            return frames, rest

        eoi = -1
        for index in range(soi + 2, length - 1):
            if buffer[index] == SOI_0 and buffer[index + 1] == EOI_1:
                eoi = index
                break
        if eoi == -1:
            return frames, buffer[soi:]

        frames.append(buffer[soi : eoi + 2])
        search_start = eoi + 2


class MjpegFrameSource:
    """Keeps the most recently decoded frame from a WDA MJPEG stream."""

    def __init__(self, url: str, now_fn=None):
        self.url = url
        self._now = now_fn or (lambda: asyncio.get_event_loop().time() * 1000)
        self._latest: dict[str, float] | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def ensure_started(self, timeout_ms: float = 3000) -> None:
        if self._stopped:
            raise RuntimeError("MjpegFrameSource has been stopped")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        if self._latest:
            return

        start = self._now()
        while self._now() - start < timeout_ms:
            if self._latest:
                return
            if self._stopped:
                raise RuntimeError("MjpegFrameSource has been stopped")
            await asyncio.sleep(_FIRST_FRAME_POLL_SECONDS)
        raise RuntimeError(f"MjpegFrameSource: no frame received within {timeout_ms}ms")

    def get_latest(self) -> dict[str, float] | None:
        if not self._latest:
            return None
        return {
            "base64": self._latest["base64"],
            "capturedAt": self._latest["capturedAt"],
        }

    def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._latest = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream("GET", self.url) as response:
                        if response.status_code >= 400:
                            raise RuntimeError(
                                f"MJPEG stream responded with {response.status_code}"
                            )
                        pending = b""
                        async for chunk in response.aiter_bytes():
                            if self._stopped:
                                return
                            pending += chunk
                            frames, rest = extract_jpeg_frames(pending)
                            if frames:
                                self._latest = {
                                    "base64": "data:image/jpeg;base64,"
                                    + base64.b64encode(frames[-1]).decode("ascii"),
                                    "capturedAt": self._now(),
                                }
                            pending = rest
                            if len(pending) > _MAX_PENDING_BYTES:
                                pending = pending[-1024:]
            except asyncio.CancelledError:
                return
            except Exception as error:  # noqa: BLE001 - reconnect on any stream error
                if self._stopped:
                    return
                logger.debug(f"MJPEG stream error, will retry: {type(error).__name__}")
            if not self._stopped:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


__all__ = ["MjpegFrameSource", "extract_jpeg_frames"]
