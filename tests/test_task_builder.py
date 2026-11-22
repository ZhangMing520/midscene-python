"""Synced from upstream packages/core/tests/unit-test/task-builder.test.ts.

The Python port exposes the locate/action halves of upstream TaskBuilder as
functions in ``midscene.core.agent.task_builder``. Cases that depend on the
upstream plan-to-task registry and planning feedback on live tasks have no
Python counterpart and are skipped with concrete reasons.
"""

from types import SimpleNamespace
from typing import Any, Dict, List
import time

import pytest

from midscene.core.agent import task_builder
from midscene.core.device import DeviceAction
from midscene.core.yaml.utils import build_detailed_locate_param


class _LocateInterface:
    interface_type = "mock"

    def __init__(self) -> None:
        self.features: List[List[float]] = []
        self.resolved: List[Any] = []

    async def cache_feature_for_point(self, center, options=None):
        self.features.append(list(center))
        return {"xpaths": ["/button"]}

    async def rect_matches_cache_feature(self, feature):
        self.resolved.append(feature)
        return None

    async def get_context(self):
        return SimpleNamespace(
            shrunk_shot_to_logical_ratio=1.0,
            screenshot_base64="data:image/png;base64,SCREENSHOT==",
            size=SimpleNamespace(width=1000, height=800),
        )


class _TaskCache:
    def __init__(self) -> None:
        self.matched: List[str] = []
        self.appended: List[Any] = []

    def match_locate_cache(self, prompt):
        self.matched.append(prompt)
        return None

    def append_locate_cache(self, prompt, feature, replace_index=None):
        self.appended.append((prompt, feature, replace_index))


class _LocateAgent:
    def __init__(self, interface, cache) -> None:
        self.interface = interface
        self.cache = cache
        self.locate_calls: List[Any] = []

    def _get_task_cache(self):
        return self.cache

    async def _write_locate_cache(
        self, prompt_str, element, cache, cacheable, replace_index=None
    ):
        return await task_builder.write_locate_cache(
            self, prompt_str, element, cache, cacheable, replace_index
        )

    async def _rect_from_cache_feature(self, feature):
        return await task_builder.rect_from_cache_feature(self, feature)

    async def _get_ui_context(self, action="locate"):
        return SimpleNamespace(
            shrunk_shot_to_logical_ratio=1.0,
            screenshot_base64="data:image/png;base64,SCREENSHOT==",
            size=SimpleNamespace(width=1000, height=800),
        )

    async def _run_locate(
        self, prompt, context, deep_locate=False, plan_located_element=None
    ):
        self.locate_calls.append((prompt, deep_locate, plan_located_element))
        return {"center": [20, 20], "description": "target"}

    def model_runtime(self, intent="default"):
        return None


@pytest.mark.parametrize("has_coordinates", [True, False])
@pytest.mark.parametrize("cacheable", [False, None])
@pytest.mark.asyncio
async def test_honors_locate_caching_independently_of_the_planner(
    has_coordinates, cacheable
):
    interface = _LocateInterface()
    cache = _TaskCache()
    agent = _LocateAgent(interface, cache)
    prompt = "" if has_coordinates else "target"
    locate_param: Dict[str, Any] = {"prompt": prompt}
    if cacheable is not None:
        locate_param["cacheable"] = cacheable
    if has_coordinates:
        locate_param["locatedPixelResult"] = {"center": [20, 20]}

    await task_builder.locate_for_action(agent, locate_param)

    assert len(agent.locate_calls) == (0 if has_coordinates else 1)
    assert interface.resolved == []
    if cacheable is False:
        assert cache.matched == []
        assert interface.features == []
        assert cache.appended == []
    else:
        assert cache.matched == [prompt]
        assert len(interface.features) == 1
        assert cache.appended == [(prompt, {"xpaths": ["/button"]}, None)]


def test_normalizes_the_deprecated_locate_deepthink_alias_before_task_reporting():
    param = build_detailed_locate_param("cart icon", {"deepThink": True})

    assert param["prompt"] == "cart icon"
    assert param["deepLocate"] is True
    assert "deepThink" not in param


def test_locates_plan_for_locate_normalizes_strings_and_deep_think():
    plan = task_builder.locate_plan_for_locate(
        {"prompt": "cart icon", "deepThink": True}
    )
    assert plan == {
        "type": "Locate",
        "thought": "",
        "param": {"prompt": "cart icon", "deepLocate": True},
    }
    assert task_builder.locate_plan_for_locate("target") == {
        "type": "Locate",
        "thought": "",
        "param": {"prompt": "target"},
    }


@pytest.mark.parametrize(
    "prompt, inherit_images",
    [
        ("target icon", True),
        ({"prompt": "target icon"}, True),
        (
            {
                "prompt": "target icon",
                "images": [
                    {"name": "local", "url": "https://example.com/local.png"}
                ],
                "convertHttpImage2Base64": False,
            },
            False,
        ),
    ],
)
@pytest.mark.asyncio
async def test_preserves_locator_prompts_while_inheriting_reference_images(
    prompt, inherit_images
):
    received = []

    async def locate(locate_param, context, runtime, abort_signal):
        received.append(locate_param["prompt"])
        return {
            "element": {
                "center": [50, 50],
                "rect": {"left": 40, "top": 40, "width": 20, "height": 20},
                "description": "target icon",
            }
        }

    multimodal_prompt = {
        "images": [{"name": "reference", "url": "https://example.com/reference.png"}],
        "convertHttpImage2Base64": True,
    }
    builder = task_builder.TaskBuilder(
        {
            "interfaceInstance": _LocateInterface(),
            "service": {"locate": locate},
            "actionSpace": [],
            "getDefaultModelRuntime": lambda: None,
        }
    )
    built = await builder.build(
        [task_builder.locate_plan_for_locate({"prompt": prompt})],
        None,
        None,
        {"multimodalPrompt": multimodal_prompt},
    )
    await built["tasks"][0]["executor"](
        {
            "task": {"timing": {}},
            "uiContext": SimpleNamespace(
                shrunk_shot_to_logical_ratio=1.0,
                screenshot_base64="data:image/png;base64,SCREENSHOT==",
                size=SimpleNamespace(width=1000, height=800),
            ),
        }
    )

    expected_prompt = (
        {"prompt": "target icon", **multimodal_prompt}
        if inherit_images
        else prompt
    )
    assert received == [expected_prompt]


@pytest.mark.asyncio
async def test_build_dispatches_finished_and_locate_plans():
    builder = task_builder.TaskBuilder(
        {
            "interfaceInstance": _LocateInterface(),
            "actionSpace": [],
            "getDefaultModelRuntime": lambda: None,
        }
    )
    built = await builder.build(
        [
            {"type": "Finished", "thought": "done"},
            task_builder.locate_plan_for_locate(
                {"prompt": "", "locatedPixelResult": {"center": [20, 20]}}
            ),
        ],
        None,
        None,
        {},
    )
    assert built["tasks"][0]["subType"] == "Finished"
    await built["tasks"][0]["executor"]({"task": {}, "uiContext": None})
    result = await built["tasks"][1]["executor"](
        {"task": {}, "uiContext": None}
    )
    assert result["output"]["element"]["center"] == [20, 20]


@pytest.mark.parametrize("separate_locate", [False, True])
@pytest.mark.asyncio
async def test_reuses_planner_coordinates_with_or_without_a_dedicated_locate_model(
    separate_locate,
):
    # Python resolves the locate runtime from the task intent, so both upstream
    # model layouts share this single resolution path.
    interface = _LocateInterface()
    agent = _LocateAgent(interface, _TaskCache())

    result = await task_builder.locate_for_action(
        agent,
        {
            "prompt": "button",
            "locatedPixelResult": {"center": [20, 20]},
        },
    )

    assert agent.locate_calls == []
    assert result["center"] == [20, 20]


@pytest.mark.asyncio
async def test_accepts_coordinate_only_planning_with_an_explicit_locate_model():
    interface = _LocateInterface()
    agent = _LocateAgent(interface, _TaskCache())

    result = await task_builder.locate_for_action(
        agent, {"locatedPixelResult": {"center": [20, 20]}}
    )

    assert result["center"] == [20, 20]
    assert agent.locate_calls == []


@pytest.mark.skip(
    reason="Python has no TaskBuilder plan-to-task handler registry; Agent.ai_act "
    "records Planning/Action Space tasks without planningFeedbackMaxLength"
)
@pytest.mark.asyncio
async def test_dispatches_plans_using_handler_registry():
    pass


@pytest.mark.asyncio
async def test_uses_promptdisplay_for_the_located_element_passed_to_an_action():
    captured = {}

    async def execute(param, device, locate_fn):
        captured["element"] = await locate_fn(param["locate"])

    tap = DeviceAction(
        name="Tap",
        description="mock tap action",
        locate_fields=["locate"],
        delay_before_runner=0,
        delay_after_runner=0,
        execute=execute,
    )

    async def locate(_prompt, _context, _runtime, _signal):
        return {
            "element": {
                "center": [50, 50],
                "rect": {"left": 40, "top": 40, "width": 20, "height": 20},
                "description": (
                    "<CONTEXT>favorite fruit rule</CONTEXT>"
                    "<LOCATE_TARGET>orange</LOCATE_TARGET>"
                ),
            }
        }

    builder = task_builder.TaskBuilder(
        {
            "interfaceInstance": _LocateInterface(),
            "service": {"locate": locate},
            "actionSpace": [tap],
            "getDefaultModelRuntime": lambda: None,
        }
    )
    plan = {
        "type": "Tap",
        "param": {
            "locate": {
                "prompt": (
                    "<CONTEXT>favorite fruit rule</CONTEXT>"
                    "<LOCATE_TARGET>orange</LOCATE_TARGET>"
                ),
                "promptDisplay": "orange",
                "context": "favorite fruit rule",
            }
        },
    }
    built = await builder.build([plan], None, None, {})
    await built["tasks"][0]["executor"](
        {"task": {"timing": {}}, "uiContext": None}
    )

    assert captured["element"]["description"] == "orange"
    assert plan["param"]["locate"]["description"] == "orange"


@pytest.mark.asyncio
async def test_throws_when_building_an_executable_task_for_an_action_outside_actionspace():
    class _Agent:
        action_space = [
            DeviceAction(name="Sleep", description="sleep", execute=lambda *a: None)
        ]
        interface = None

        async def _locate_for_action(self, locate_param):
            return locate_param

    with pytest.raises(ValueError, match="Action type 'Tap' is not in the current action space"):
        await task_builder.execute_planning_action(
            _Agent(), {"type": "Tap", "param": {}}
        )


@pytest.mark.asyncio
async def test_supports_fast_path_action_delays_for_system_actions():
    default_events = []
    fast_events = []

    class _HookedInterface:
        def __init__(self, events):
            self.events = events

        async def before_invoke_action(self, name, param, signal=None):
            self.events.append(("before", time.monotonic()))

        async def after_invoke_action(self, name, param, signal=None):
            self.events.append(("after", time.monotonic()))

        async def get_context(self):
            return SimpleNamespace(
                shrunk_shot_to_logical_ratio=1.0,
                screenshot_base64="",
                size=SimpleNamespace(width=1000, height=800),
            )

    async def default_call(_param, _device, _locate_fn):
        default_events.append(("call", time.monotonic()))

    async def fast_call(_param, _device, _locate_fn):
        fast_events.append(("call", time.monotonic()))

    default_action = DeviceAction(
        name="DefaultExit",
        description="default exit action",
        execute=default_call,
    )
    fast_action = DeviceAction(
        name="FastExit",
        description="fast exit action",
        delay_before_runner=0,
        delay_after_runner=0,
        execute=fast_call,
    )

    def build(interface, action, plan_type):
        return task_builder.TaskBuilder(
            {
                "interfaceInstance": interface,
                "actionSpace": [action],
                "getDefaultModelRuntime": lambda: None,
            }
        )

    default_builder = build(
        _HookedInterface(default_events), default_action, "DefaultExit"
    )
    fast_builder = build(_HookedInterface(fast_events), fast_action, "FastExit")
    default_tasks = (
        await default_builder.build(
            [{"type": "DefaultExit", "thought": "", "param": {}}], None, None
        )
    )["tasks"]
    fast_tasks = (
        await fast_builder.build(
            [{"type": "FastExit", "thought": "", "param": {}}], None, None
        )
    )["tasks"]

    task_context = {"task": {"timing": {}}, "uiContext": None}
    await default_tasks[0]["executor"](task_context)
    await fast_tasks[0]["executor"](task_context)

    assert [event[0] for event in default_events] == ["before", "call", "after"]
    default_before = default_events[0][1]
    default_call_at = default_events[1][1]
    default_after = default_events[2][1]
    assert default_call_at - default_before >= 0.15
    assert default_after - default_call_at >= 0.25

    assert [event[0] for event in fast_events] == ["before", "call", "after"]
    fast_before = fast_events[0][1]
    fast_call_at = fast_events[1][1]
    fast_after = fast_events[2][1]
    assert fast_call_at - fast_before < 0.1
    assert fast_after - fast_call_at < 0.1


@pytest.mark.skip(
    reason="Python ExecutionTask has no planningFeedback field on the running task"
)
@pytest.mark.asyncio
async def test_allows_actions_to_attach_planning_feedback_to_the_running_task():
    pass


@pytest.mark.parametrize(
    "distance_unit,distance,ratio,expected",
    [
        ("model-input-image-pixel", 120, 1.5, 80),
        ("device-logical", 120, None, 120),
        pytest.param(
            "model-input-image-pixel",
            None,
            1.5,
            100,
            marks=pytest.mark.skip(
                reason="Python action definitions do not declare JSON-schema "
                "defaults, so a missing distance is left to the platform action"
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_preserves_the_distance_unit_and_device_unit_defaults(
    distance_unit, distance, ratio, expected
):
    captured: List[Dict[str, Any]] = []

    async def execute(param, device, locate):
        captured.append(dict(param))

    action = DeviceAction(
        name="CustomMove",
        description="custom move",
        param_schema={"distance": {"type": "number"}},
        distance_fields=["distance"],
        execute=execute,
    )

    class _Agent:
        action_space = [action]
        interface = None

        async def _locate_for_action(self, locate_param):
            return locate_param

    await task_builder.execute_planning_action(
        _Agent(),
        {"type": "CustomMove", "param": {"distance": distance}},
        distance_ratio=ratio,
    )

    assert captured[0]["distance"] == expected
