"""Synced from upstream
``packages/ios/tests/unit-test/mjpeg-frame-source.test.ts``.
"""

import asyncio
import base64

import pytest

from midscene.ios.mjpeg_frame_source import (
    MjpegFrameSource,
    extract_jpeg_frames,
)


def _jpeg(tag):
    # A minimal "JPEG": SOI (FF D8) + a tag byte + EOI (FF D9).
    return bytes([0xFF, 0xD8, tag, 0xFF, 0xD9])


def test_extracts_a_single_complete_frame_and_leaves_no_remainder():
    """extracts a single complete frame and leaves no remainder"""
    frames, rest = extract_jpeg_frames(_jpeg(0x01))
    assert len(frames) == 1
    assert list(frames[0]) == [0xFF, 0xD8, 0x01, 0xFF, 0xD9]
    assert len(rest) == 0


def test_extracts_multiple_frames_in_order():
    """extracts multiple frames in order"""
    buffer = _jpeg(0x01) + _jpeg(0x02) + _jpeg(0x03)
    frames, rest = extract_jpeg_frames(buffer)
    assert len(frames) == 3
    assert [frame[2] for frame in frames] == [0x01, 0x02, 0x03]
    assert len(rest) == 0


def test_ignores_boundary_header_bytes_before_the_soi():
    """ignores boundary/header bytes before the SOI"""
    boundary = b"--BoundaryString\r\nContent-Type: image/jpeg\r\n\r\n"
    frames, rest = extract_jpeg_frames(boundary + _jpeg(0x07))
    assert len(frames) == 1
    assert frames[0][2] == 0x07
    assert len(rest) == 0


def test_carries_an_incomplete_frame_soi_without_eoi_into_rest():
    """carries an incomplete frame (SOI without EOI) into rest"""
    partial = bytes([0xFF, 0xD8, 0xAA, 0xBB])  # no EOI yet
    frames, rest = extract_jpeg_frames(partial)
    assert len(frames) == 0
    assert list(rest) == [0xFF, 0xD8, 0xAA, 0xBB]


def test_reassembles_a_frame_split_across_two_chunks():
    """reassembles a frame split across two chunks"""
    full = _jpeg(0x42)
    chunk_a = full[0:3]  # FF D8 42
    chunk_b = full[3:]  # FF D9

    first_frames, first_rest = extract_jpeg_frames(chunk_a)
    assert len(first_frames) == 0

    second_frames, second_rest = extract_jpeg_frames(first_rest + chunk_b)
    assert len(second_frames) == 1
    assert second_frames[0][2] == 0x42
    assert len(second_rest) == 0


def test_keeps_a_trailing_0xff_that_may_begin_a_split_soi_marker():
    """keeps a trailing 0xFF that may begin a split SOI marker"""
    frames, rest = extract_jpeg_frames(_jpeg(0x01) + bytes([0xFF]))
    assert len(frames) == 1
    assert list(rest) == [0xFF]


@pytest.mark.skip(
    reason="Python IOSDevice does not accept wdaMjpegPort and exposes no "
    "openFrameSource attribute"
)
def test_does_not_expose_open_frame_source_by_default():
    """does not expose openFrameSource by default"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice has no wdaMjpegFrameSource option or "
    "openFrameSource() method"
)
def test_exposes_open_frame_source_when_explicitly_enabled():
    """exposes openFrameSource when explicitly enabled"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice exposes no mjpegStreamUrl; the MJPEG source is "
    "constructed directly from a URL"
)
def test_builds_the_stream_url_from_the_per_device_wda_mjpeg_port_multi_device():
    """builds the stream URL from the per-device wdaMjpegPort (multi-device)"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice exposes no mjpegStreamUrl or wdaBaseUrl/wdaMjpeg "
    "separation"
)
def test_keeps_a_gateway_api_url_separate_from_the_default_local_mjpeg_stream():
    """keeps a gateway API URL separate from the default local MJPEG stream"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice has no wdaMjpegUrl/wdaMjpegFrameSource options "
    "and exposes no mjpegStreamUrl/openFrameSource"
)
def test_uses_an_independent_https_mjpeg_stream_url_with_a_path_and_query():
    """uses an independent HTTPS MJPEG stream URL with a path and query"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice does not accept wdaMjpegUrl/wdaMjpegPort; the "
    "validation exists in midscene.ios.wda_options.assert_wda_connection_options "
    "but is not wired into the device constructor"
)
def test_rejects_conflicting_or_invalid_mjpeg_stream_options_without_revealing_the_url():
    """rejects conflicting or invalid MJPEG stream options without revealing the URL"""
    pass


@pytest.mark.skip(
    reason="Python IOSDevice exposes no openFrameSource(), "
    "ensureMjpegFrameSource, or mjpegFrameSource field to wrap/tear down"
)
def test_wraps_the_mjpeg_stream_as_a_frame_source_identity_decode_stop_tears_down():
    """wraps the MJPEG stream as a frame source (identity decode, stop tears down)"""
    pass


@pytest.mark.asyncio
async def test_decodes_frames_from_a_streamed_mjpeg_response_and_exposes_the_latest(
    monkeypatch,
):
    """decodes frames from a streamed MJPEG response and exposes the latest"""
    from midscene.ios import mjpeg_frame_source as module

    full = _jpeg(0x01) + _jpeg(0x02)

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def aiter_bytes(self):
            yield full[0:4]
            yield full[4:]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def stream(self, method, url):
            assert method == "GET"
            assert url == "http://localhost:9100"
            return FakeStreamResponse()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)

    clock = {"value": 1000}

    def now():
        clock["value"] += 1
        return clock["value"]

    source = MjpegFrameSource("http://localhost:9100", now)
    await source.ensure_started(2000)
    latest = source.get_latest()
    assert latest is not None
    assert latest["base64"].startswith("data:image/jpeg;base64,")
    # last frame in the stream is jpeg(0x02)
    decoded = base64.b64decode(latest["base64"].replace("data:image/jpeg;base64,", ""))
    assert decoded[2] == 0x02
    source.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_does_not_include_a_signed_stream_url_in_a_startup_timeout(
    monkeypatch,
):
    """does not include a signed stream URL in a startup timeout"""
    from midscene.ios import mjpeg_frame_source as module

    async def never_runs(_self):
        await asyncio.sleep(10)

    monkeypatch.setattr(module.MjpegFrameSource, "_run", never_runs)

    clock = {"value": 0}

    def now():
        clock["value"] += 1000
        return clock["value"]

    source = MjpegFrameSource("https://stream.example/live/mjpeg?token=secret", now)
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await source.ensure_started(3000)
    finally:
        source.stop()
        await asyncio.sleep(0)

    assert "no frame received within 3000ms" in str(excinfo.value)
    assert "secret" not in str(excinfo.value)
