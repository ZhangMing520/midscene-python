"""Synced from upstream packages/core/tests/unit-test/ui-observer.test.ts."""

import asyncio
import base64
import io
from pathlib import Path

import pytest

from midscene.core.agent.ui_observer import (
    UIObservationImpl,
    UIObserverImpl,
    ui_context_from_observation_record,
)
from midscene.core.types import NodeType, Rect, Size, UIContext, UINode, UITree
from midscene.shared.agent_tools.observation_record import (
    UIObservationRecordWriter,
)
from tests.core_helpers import MockInterface, make_png_base64


def _agent(**options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    return Agent(
        MockInterface(),
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "m",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            },
            **options,
        ),
    )


def _png_data_url(width=8, height=6):
    return "data:image/png;base64," + make_png_base64(width, height)


def _jpeg_data_url(width=2, height=2):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(buffer, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def _representative(width=2, height=2):
    return UIContext(
        screenshot_base64=_jpeg_data_url(width, height),
        size=Size(width=width, height=height),
        content=[],
        tree=UITree(
            node=UINode(
                id="root",
                content="",
                rect=Rect(left=0, top=0, width=0, height=0),
                center=(0, 0),
                node_type=NodeType.CONTAINER,
            )
        ),
        shrunk_shot_to_logical_ratio=1.0,
    )


class _FakeSource:
    def __init__(self):
        self.current = None
        self.decoded_batches = []
        self.stopped = 0

    def latest(self):
        return self.current

    async def decode(self, refs):
        self.decoded_batches.append(list(refs))
        return [_png_data_url() for _ in refs]

    def stop(self):
        self.stopped += 1


def _make_deps(tmp_path, fake):
    screenshot_calls = []
    stopped = []

    async def capture_raw_screenshot():
        screenshot_calls.append(True)
        return _png_data_url()

    async def open_frame_source():
        return fake

    def create_insight(_record):
        class _Insight:
            async def ai_query(self, *args, **kwargs):
                return None

            async def ai_boolean(self, *args, **kwargs):
                return True

            async def ai_number(self, *args, **kwargs):
                return 0

            async def ai_string(self, *args, **kwargs):
                return ""

            async def ai_ask(self, *args, **kwargs):
                return ""

            async def ai_assert(self, *args, **kwargs):
                return None

        return _Insight()

    deps = {
        "openFrameSource": open_frame_source,
        "captureRawScreenshot": capture_raw_screenshot,
        "capturePreparedRepresentative": lambda: _representative(),
        "createInsight": create_insight,
        "onStopped": lambda: stopped.append(True),
        "observationRecordWriter": UIObservationRecordWriter(
            str(tmp_path / "observation.json")
        ),
    }
    return deps, screenshot_calls, stopped


def _jpeg_magic(path):
    return list(Path(path).read_bytes()[:3])


class TestUIObserverImpl:
    @pytest.mark.asyncio
    async def test_exposes_records_only_through_the_observation_returned_by_stop(
        self, tmp_path
    ):
        fake = _FakeSource()
        fake.current = {"ref": "f0", "capturedAt": 0}
        deps, _, _ = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        assert not hasattr(observer, "export_record")
        observation = await observer.stop()
        record = await observation.export_record()
        assert record["type"] == "midscene_ui_observation"
        assert record["version"] == 1
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_persists_source_frames_aligns_representative_and_stops_source(
        self, tmp_path
    ):
        fake = _FakeSource()
        fake.current = {"ref": "f0", "capturedAt": 0}
        deps, _, stopped = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        fake.current = {"ref": "f1", "capturedAt": 100}
        await asyncio.sleep(0.25)
        observation = await observer.stop()
        record = await observation.export_record()

        assert observer.buffered_frame_count >= 2
        assert observation.frame_count == len(record["frames"])
        assert observation.ended_at >= observation.started_at
        assert stopped == [True]
        assert fake.stopped == 1
        assert len(record["frames"]) >= 3
        assert all(frame["mimeType"] == "image/jpeg" for frame in record["frames"])
        assert _jpeg_magic(record["frames"][0]["path"]) == [0xFF, 0xD8, 0xFF]
        assert _jpeg_magic(record["frames"][-1]["path"]) == [0xFF, 0xD8, 0xFF]
        assert "base64" not in record["frames"][0]
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_decodes_opaque_source_handles_in_bounded_batches_and_detaches_exports(
        self, tmp_path
    ):
        fake = _FakeSource()
        deps, _, _ = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200, "maxFrames": 30})
        for index in range(10):
            observer._push_frame({"ref": f"f{index}", "capturedAt": index})
        observer._source = fake
        observation = await observer.stop()
        first = await observation.export_record()
        second = await observation.export_record()

        assert first is not second
        first["frames"].clear()
        assert len(second["frames"]) == 11
        assert len(fake.decoded_batches) == 3
        assert all(len(batch) <= 4 for batch in fake.decoded_batches)
        assert first["frames"] == []
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_exports_every_buffered_frame_up_to_the_configured_cap(
        self, tmp_path
    ):
        fake = _FakeSource()
        deps, _, _ = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200, "maxFrames": 30})
        for index in range(30):
            observer._push_frame({"ref": f"f{index}", "capturedAt": index})
        observer._source = fake
        observation = await observer.stop()
        record = await observation.export_record()
        assert len(record["frames"]) == 31
        assert sum(len(batch) for batch in fake.decoded_batches) == 30
        assert all(frame["mimeType"] == "image/jpeg" for frame in record["frames"])
        await observer.dispose()

    def test_smart_thinning_preserves_change_points_and_temporal_endpoints(
        self, tmp_path
    ):
        observer = UIObserverImpl(
            _make_deps(tmp_path, _FakeSource())[0],
            {"intervalMs": 200, "maxFrames": 10},
        )
        refs = ["a"] * 5 + ["b"] * 5 + ["c"] * 6
        for captured_at, ref in enumerate(refs):
            observer._push_frame({"ref": ref, "capturedAt": captured_at})
        kept = [frame["ref"] for frame in observer._frames]
        assert "a" in kept and "b" in kept and "c" in kept
        assert kept[0] == "a"
        assert kept[-1] == "c"

    def test_enforces_max_frames_even_when_every_frame_is_a_change_point(
        self, tmp_path
    ):
        observer = UIObserverImpl(
            _make_deps(tmp_path, _FakeSource())[0],
            {"intervalMs": 200, "maxFrames": 10},
        )
        for index in range(16):
            observer._push_frame({"ref": f"frame-{index}", "capturedAt": index})
        assert len(observer._frames) == 10
        assert observer._frames[0]["ref"] == "frame-0"
        assert observer._frames[-1]["ref"] == "frame-15"

    @pytest.mark.asyncio
    async def test_disposes_the_file_backed_record_after_it_is_no_longer_needed(
        self, tmp_path
    ):
        fake = _FakeSource()
        deps, _, _ = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        persisted = deps["observationRecordWriter"].persist_frame(_png_data_url(), 100)
        observer._push_frame(
            {
                "ref": persisted["path"],
                "capturedAt": 100,
                "persisted": persisted,
            }
        )
        observation = await observer.stop()
        record = await observation.export_record()
        assert Path(record["frames"][0]["path"]).read_bytes()
        await observation.dispose()
        assert not Path(record["frames"][0]["path"]).exists()
        with pytest.raises(RuntimeError, match="disposed"):
            await observation.export_record()

    @pytest.mark.asyncio
    async def test_watchdog_auto_stops_and_can_also_be_disabled(self, tmp_path):
        fake = _FakeSource()
        fake.current = {"ref": "f0", "capturedAt": 0}
        deps, _, stopped = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 100, "watchdogMs": 100})
        await observer.start()
        await asyncio.sleep(0.3)
        assert observer._stopped is True
        await observer.stop()
        assert stopped == [True]
        await observer.dispose()

        fake2 = _FakeSource()
        fake2.current = {"ref": "f0", "capturedAt": 0}
        deps2, _, stopped2 = _make_deps(tmp_path / "second", fake2)
        Path(tmp_path / "second").mkdir(exist_ok=True)
        disabled = UIObserverImpl(deps2, {"intervalMs": 100, "watchdogMs": 0})
        await disabled.start()
        await asyncio.sleep(0.2)
        assert disabled._stopped is False
        assert stopped2 == []
        await disabled.stop()
        await disabled.dispose()

    @pytest.mark.asyncio
    async def test_stop_and_export_are_idempotent(self, tmp_path):
        fake = _FakeSource()
        fake.current = {"ref": "f0", "capturedAt": 0}
        deps, _, stopped = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        first_observation = await observer.stop()
        second_observation = await observer.stop()
        first = await first_observation.export_record()
        second = await second_observation.export_record()
        assert stopped == [True]
        assert second_observation is first_observation
        assert second is not first
        assert second == first
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_persists_fallback_screenshots_immediately_as_jpeg_files(
        self, tmp_path
    ):
        deps, screenshot_calls, _ = _make_deps(tmp_path, None)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        await asyncio.sleep(0.25)
        observation = await observer.stop()
        record = await observation.export_record()
        assert screenshot_calls
        assert all(frame["mimeType"] == "image/jpeg" for frame in record["frames"])
        assert _jpeg_magic(record["frames"][0]["path"]) == [0xFF, 0xD8, 0xFF]
        assert "base64" not in observer._frames[0]["ref"]
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_falls_back_when_opening_the_frame_source_throws(self, tmp_path):
        screenshot_calls = []

        async def failing_source():
            raise RuntimeError("stream unavailable")

        async def capture():
            screenshot_calls.append(True)
            return _png_data_url()

        deps = {
            "openFrameSource": failing_source,
            "captureRawScreenshot": capture,
            "capturePreparedRepresentative": lambda: _representative(),
            "createInsight": lambda _record: None,
            "observationRecordWriter": UIObservationRecordWriter(
                str(tmp_path / "observation.json")
            ),
        }
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        observation = await observer.stop()
        await observation.export_record()
        assert screenshot_calls
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_stop_calls_wait_for_the_same_finalization(self, tmp_path):
        fake = _FakeSource()
        fake.current = {"ref": "f0", "capturedAt": 0}
        deps, _, stopped = _make_deps(tmp_path, fake)
        observer = UIObserverImpl(deps, {"intervalMs": 200})
        await observer.start()
        first, second = await asyncio.gather(observer.stop(), observer.stop())
        assert first is second
        assert stopped == [True]
        await observer.dispose()


class TestUIObservationImpl:
    @pytest.mark.asyncio
    async def test_rejects_live_dom_options_before_delegating_an_observation_insight(
        self,
    ):
        calls = []

        class _Insight:
            async def ai_boolean(self, *args, **kwargs):
                calls.append(args)
                return True

        observation = UIObservationImpl(
            {
                "type": "midscene_ui_observation",
                "version": 1,
                "startedAt": 100,
                "endedAt": 200,
                "frames": [
                    {
                        "path": "/tmp/unused.png",
                        "mimeType": "image/png",
                        "capturedAt": 150,
                    }
                ],
                "shotSize": {"width": 100, "height": 100},
                "shrunkShotToLogicalRatio": 1,
            },
            _Insight(),
        )
        with pytest.raises(ValueError, match="does not support domIncluded"):
            await observation.ai_boolean(
                "is the old toast visible?", {"domIncluded": True}
            )
        assert calls == []

    @pytest.mark.asyncio
    async def test_keeps_failed_observation_cleanup_retryable(self):
        attempts = []
        disposed = []

        def dispose_record():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("directory is busy")

        observation = UIObservationImpl(
            {
                "type": "midscene_ui_observation",
                "version": 1,
                "startedAt": 100,
                "endedAt": 200,
                "frames": [
                    {
                        "path": "/tmp/unused.png",
                        "mimeType": "image/png",
                        "capturedAt": 150,
                    }
                ],
                "shotSize": {"width": 100, "height": 100},
                "shrunkShotToLogicalRatio": 1,
            },
            None,
            dispose_record,
            lambda: disposed.append(True),
        )
        with pytest.raises(RuntimeError, match="directory is busy"):
            await observation.dispose()
        assert disposed == []
        await observation.dispose()
        assert len(attempts) == 2
        assert disposed == [True]


class TestUIContextFromObservationRecord:
    def test_rebuilds_the_screenshot_sequence(self, tmp_path):
        frame_path = tmp_path / "frame.png"
        frame_path.write_bytes(base64.b64decode(make_png_base64(10, 10)))
        record = {
            "type": "midscene_ui_observation",
            "version": 1,
            "startedAt": 100,
            "endedAt": 200,
            "frames": [
                {
                    "path": str(frame_path),
                    "mimeType": "image/png",
                    "capturedAt": 150,
                }
            ],
            "shotSize": {"width": 10, "height": 10},
            "shrunkShotToLogicalRatio": 2,
        }
        context = ui_context_from_observation_record(record)
        assert context.shrunk_shot_to_logical_ratio == 2
        assert len(context.screenshot_sequence) == 1
        assert context.screenshot_sequence[0].startswith("data:image/png;base64,")
        assert context.screenshot_base64 == context.screenshot_sequence[-1]

    def test_rejects_invalid_record_shapes(self):
        base = {
            "type": "midscene_ui_observation",
            "version": 1,
            "startedAt": 100,
            "endedAt": 200,
            "frames": [
                {
                    "path": "/tmp/x.png",
                    "mimeType": "image/png",
                    "capturedAt": 150,
                }
            ],
            "shotSize": {"width": 10, "height": 10},
            "shrunkShotToLogicalRatio": 1,
        }
        with pytest.raises(ValueError, match="invalid UI observation record"):
            ui_context_from_observation_record({**base, "version": 2})
        with pytest.raises(ValueError, match="contains no frames"):
            ui_context_from_observation_record({**base, "frames": []})
        with pytest.raises(ValueError, match="shot width must be positive"):
            ui_context_from_observation_record(
                {**base, "shotSize": {"width": 0, "height": 10}}
            )


# ---------------------------------------------------------------------------
# Python Agent-backed observer (kept in addition to the upstream impl cases)
# ---------------------------------------------------------------------------


def _tagged_contexts(agent, state, fail_first=0):
    async def fake_context(action=""):
        base = await agent.interface.get_context()
        state["n"] += 1
        if state["n"] <= fail_first:
            raise RuntimeError("capture exploded")
        return base.model_copy(update={"screenshot_base64": f"frame-{state['n']}"})

    agent.get_ui_context = fake_context


@pytest.mark.asyncio
async def test_agent_observer_watchdog_auto_stops_and_can_also_be_disabled():
    agent = _agent()
    observer = agent.start_observing({"intervalMs": 100, "watchdogMs": 300})
    await observer.start()
    await asyncio.sleep(0.6)
    assert observer._stop_requested is True
    observation = await observer.stop()
    assert observation is observer._observation
    assert observation.frame_count >= 1
    await observer.dispose()

    disabled = agent.start_observing({"intervalMs": 100, "watchdogMs": 0})
    await disabled.start()
    await asyncio.sleep(0.3)
    assert disabled._stop_requested is False
    await disabled.stop()
    await disabled.dispose()


@pytest.mark.asyncio
async def test_agent_observer_rejects_live_dom_options():
    agent = _agent()
    observer = agent.start_observing({"intervalMs": 50, "watchdogMs": 0})
    await observer.start()
    observation = await observer.stop()
    with pytest.raises(ValueError) as exc:
        await observation.ai_boolean("is the old toast visible?", {"domIncluded": True})
    assert "does not support domIncluded" in str(exc.value)
    await observation.dispose()


@pytest.mark.asyncio
async def test_agent_observer_concurrent_stop_calls_wait_for_the_same_finalization():
    agent = _agent()
    observer = agent.start_observing(
        {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
    )
    await observer.start()
    first, second = await asyncio.gather(observer.stop(), observer.stop())
    assert first is second
    assert first.frame_count >= 1
    await observer.dispose()
