"""Synced from upstream
``packages/android/tests/unit-test/visual-action-registry.test.ts``.
"""

import pytest

from midscene.android.visual_action_registry import (
    create_visual_action_registry,
)


@pytest.mark.asyncio
async def test_runs_the_completion_hook_after_dispatch_with_the_registered_action_name():
    """runs the completion hook after dispatch with the registered action name"""
    order = []

    async def dispatch(uri):
        order.append("dispatch")
        return f"launched:{uri}"

    async def on_action_settled(name):
        order.append(("settled", name))

    actions = create_visual_action_registry({"launch": dispatch}, on_action_settled)

    assert await actions["launch"]("com.example.app") == "launched:com.example.app"
    assert order == ["dispatch", ("settled", "launch")]


@pytest.mark.asyncio
async def test_settles_a_composite_action_only_once():
    """settles a composite action only once"""
    dispatched = []
    settled = []

    async def dispatch_step():
        dispatched.append(True)

    async def swipe(repeat):
        for _ in range(repeat):
            await dispatch_step()

    async def on_action_settled(name):
        settled.append(name)

    actions = create_visual_action_registry({"swipe": swipe}, on_action_settled)

    await actions["swipe"](3)

    assert len(dispatched) == 3
    assert settled == ["swipe"]


@pytest.mark.asyncio
async def test_settles_an_action_after_a_dispatch_that_fails():
    """settles an action after a dispatch that fails"""
    action_error = RuntimeError("second gesture failed")
    events = []
    attempts = {"count": 0}

    async def dispatch_step():
        attempts["count"] += 1
        events.append(("dispatch", attempts["count"]))
        if attempts["count"] == 2:
            raise action_error

    async def swipe():
        await dispatch_step()
        await dispatch_step()

    async def on_action_settled(name):
        events.append(("settled", name))

    actions = create_visual_action_registry({"swipe": swipe}, on_action_settled)

    with pytest.raises(RuntimeError) as excinfo:
        await actions["swipe"]()

    assert excinfo.value is action_error
    assert events == [
        ("dispatch", 1),
        ("dispatch", 2),
        ("settled", "swipe"),
    ]


@pytest.mark.skip(
    reason="upstream statically parses packages/android/src/device.ts with the "
    "TypeScript compiler API; Python device.py has no AndroidDevice.visualActions "
    "source structure to inspect"
)
def test_keeps_public_visual_mutations_behind_the_registry():
    """keeps public visual mutations behind the registry"""
    pass


@pytest.mark.skip(
    reason="upstream statically parses AndroidDevice methods in device.ts with "
    "the TypeScript compiler API; there is no equivalent Python source-level "
    "getAdb() contract to audit"
)
def test_requires_every_public_adb_caller_to_be_reviewed_as_non_visual():
    """requires every public ADB caller to be reviewed as non-visual"""
    pass


@pytest.mark.skip(
    reason="upstream pairs private *Raw methods with public registry delegates by "
    "statically parsing device.ts; Python device.py has no *Raw/visualActions "
    "naming convention to inspect"
)
def test_delegates_every_public_method_with_a_raw_implementation_to_the_registry():
    """delegates every public method with a raw implementation to the registry"""
    pass
