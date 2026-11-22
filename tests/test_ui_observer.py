"""Synced from upstream packages/core/tests/unit-test/ui-observer.test.ts.

Upstream constructs UIObserverImpl with an injected frame source, record
writer and insight factory. The Python UIObserver records screenshots through
the Agent interface, so cases that depend on DeviceFrameSource persistence /
exportRecord have no Python counterpart and are skipped with a reason.
"""

import asyncio

import pytest

from tests.core_helpers import MockInterface


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


def _tagged_contexts(agent, state, fail_first=0):
    async def fake_context(action=""):
        base = await agent.interface.get_context()
        state["n"] += 1
        if state["n"] <= fail_first:
            raise RuntimeError("capture exploded")
        return base.model_copy(update={"screenshot_base64": f"frame-{state['n']}"})

    agent.get_ui_context = fake_context


@pytest.mark.asyncio
async def test_watchdog_auto_stops_and_can_also_be_disabled():
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
async def test_rejects_live_dom_options_before_delegating_an_observation_insight():
    agent = _agent()
    observer = agent.start_observing({"intervalMs": 50, "watchdogMs": 0})
    await observer.start()
    observation = await observer.stop()
    with pytest.raises(ValueError) as exc:
        await observation.ai_boolean("is the old toast visible?", {"domIncluded": True})
    assert "does not support domIncluded" in str(exc.value)
    await observation.dispose()


@pytest.mark.asyncio
async def test_concurrent_stop_calls_wait_for_the_same_finalization():
    agent = _agent()
    observer = agent.start_observing(
        {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
    )
    await observer.start()
    first, second = await asyncio.gather(observer.stop(), observer.stop())
    assert first is second
    assert first.frame_count >= 1
    await observer.dispose()


@pytest.mark.skip(
    reason="Python UIObserver has no DeviceFrameSource/persisted-record pipeline; "
    "frames are owned as screenshot base64 and stop() returns a UIObservation "
    "without exportRecord()"
)
def test_exposes_records_only_through_the_observation_returned_by_stop():
    pass


@pytest.mark.skip(
    reason="Python UIObserver does not expose pushFrame(); buffer thinning is "
    "internal and driven by real screenshot sampling"
)
def test_enforces_max_frames_even_when_every_frame_is_a_change_point():
    pass


@pytest.mark.skip(
    reason="Python UIObserver records through the Agent interface; there is no "
    "frame source, record writer, or persisted JPEG frame to assert on"
)
def test_persists_source_frames_aligns_the_representative_and_stops_the_source():
    pass
