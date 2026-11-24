"""Synced from upstream packages/core/tests/unit-test/bbox-locate-cache.test.ts."""

import base64
from typing import Any

import pytest

from midscene.core.agent.agent_options import AgentOptions
from midscene.core.types import (
    BaseElement,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)


def make_png_base64(width: int = 320, height: int = 240) -> str:
    import io

    from PIL import Image

    image = Image.new("RGB", (width, height), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_empty_tree() -> UITree:
    return UITree(
        node=UINode(
            id="root",
            content="",
            rect=Rect(left=0, top=0, width=0, height=0),
            center=(0, 0),
            node_type=NodeType.CONTAINER,
        )
    )


class MockInterface:
    def __init__(self):
        self.interface_type = "web"
        self._context = None
        self.tapped: list[tuple] = []
        self.typed: list[str] = []
        self.keys: list[str] = []
        self.scrolled: list[tuple] = []

    async def get_context(self) -> UIContext:
        return UIContext(
            screenshot_base64=make_png_base64(),
            size=Size(width=320, height=240),
            content=[
                BaseElement(
                    id="test_element",
                    content="Test Button",
                    rect=Rect(left=100, top=100, width=200, height=50),
                    center=(200, 125),
                    node_type=NodeType.BUTTON,
                )
            ],
            tree=make_empty_tree(),
        )

    async def action_space(self):
        return ["tap", "input", "scroll"]

    async def tap(self, x, y):
        self.tapped.append((x, y))

    async def input_text(self, text):
        self.typed.append(text)

    async def keyboard_press(self, key):
        self.keys.append(key)

    async def clear_input(self):
        pass

    async def replace_input(self, text):
        self.typed.append(text)

    async def scroll(self, direction, distance=None, **kwargs):
        self.scrolled.append((direction, distance, kwargs))


class _CacheInterface(MockInterface):
    """Mock interface exposing the optional locate-cache hooks."""

    def __init__(self):
        super().__init__()
        self.features: list[list] = []
        self.feature_options: list[Any] = []
        self.resolved: list[dict[str, Any]] = []
        self.rect_to_return: Rect | None = Rect(left=10, top=20, width=30, height=40)

    async def cache_feature_for_point(self, center, options=None):
        self.features.append(list(center))
        self.feature_options.append(options)
        return {"xpaths": ["/html/body/button[1]"]}

    async def rect_matches_cache_feature(self, feature):
        self.resolved.append(feature)
        return self.rect_to_return


@pytest.mark.asyncio
async def test_should_hit_locate_cache_on_second_execution_without_bbox(
    tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(interface, AgentOptions(cache_id="locate-hit"))
    agent._get_task_cache().append_locate_cache("the button", {"xpaths": ["/cached"]})

    async def fail_locate(*args, **kwargs):
        raise AssertionError("AI locate must not run on a cache hit")

    monkeypatch.setattr(agent, "_run_locate", fail_locate)
    result = await agent._locate_for_action({"prompt": "the button"})

    assert result["center"] == [25.0, 40.0]
    assert result["rect"] == Rect(left=10, top=20, width=30, height=40)
    assert interface.resolved == [{"xpaths": ["/cached"]}]


@pytest.mark.asyncio
async def test_should_write_locate_cache_even_when_bbox_is_used_for_positioning(
    tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(interface, AgentOptions(cache_id="locate-write"))

    async def fake_locate(*args, **kwargs):
        return {
            "center": [25, 40],
            "rect": Rect(left=10, top=20, width=30, height=40),
        }

    monkeypatch.setattr(agent, "_run_locate", fake_locate)
    await agent._locate_for_action({"prompt": "the button"})

    assert interface.features == [[25.0, 40.0]]
    assert interface.feature_options[0]["target_description"] == "the button"
    reloaded = TaskCache(cache_id="locate-write", enabled=True)
    assert reloaded.match_locate_cache("the button")["cache"] == {
        "xpaths": ["/html/body/button[1]"]
    }


@pytest.mark.asyncio
async def test_should_respect_cacheable_false_option(tmp_path, monkeypatch):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(interface, AgentOptions(cache_id="locate-nocache"))

    async def fake_locate(*args, **kwargs):
        return {"center": [1, 2], "rect": None}

    monkeypatch.setattr(agent, "_run_locate", fake_locate)
    await agent._locate_for_action({"prompt": "the button", "cacheable": False})

    assert interface.features == []
    assert agent._get_task_cache().cache["caches"] == []


@pytest.mark.asyncio
async def test_should_update_cache_when_cached_xpath_becomes_invalid(
    tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.task_cache import TaskCache

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    interface.rect_to_return = None
    agent = Agent(interface, AgentOptions(cache_id="locate-stale"))
    agent._get_task_cache().append_locate_cache("the button", {"xpaths": ["/stale"]})

    async def fake_locate(*args, **kwargs):
        return {"center": [5, 6], "rect": None}

    monkeypatch.setattr(agent, "_run_locate", fake_locate)
    result = await agent._locate_for_action({"prompt": "the button"})

    assert result["center"] == [5, 6]
    assert interface.features == [[5.0, 6.0]]
    reloaded = TaskCache(cache_id="locate-stale", enabled=True)
    assert reloaded.match_locate_cache("the button")["cache"] == {
        "xpaths": ["/html/body/button[1]"]
    }


@pytest.mark.asyncio
async def test_should_write_locate_cache_for_plan_coordinates(tmp_path, monkeypatch):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(interface, AgentOptions(cache_id="locate-plan"))
    result = await agent._locate_for_action(
        {
            "prompt": "the button",
            "locatedPixelResult": {"center": [7, 8]},
        }
    )

    assert result == {"center": [7, 8]}
    assert interface.features == [[7.0, 8.0]]


@pytest.mark.asyncio
async def test_non_cacheable_planner_skips_all_caches(tmp_path, monkeypatch):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(
        interface,
        AgentOptions(
            cache_id="locate-nocache-planner",
            model_config={
                "MIDSCENE_MODEL_NAME": "mock-model",
                "MIDSCENE_MODEL_API_KEY": "sk-test",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "vlm-ui-tars",
            },
        ),
    )
    cache = agent._get_task_cache()
    cache.append_locate_cache("the button", {"xpaths": ["/cached"]})
    cache.append_plan_cache("another task", "- type: Tap")

    async def fake_locate(*args, **kwargs):
        return {"center": [25, 40], "rect": None}

    monkeypatch.setattr(agent, "_run_locate", fake_locate)
    plans = [
        {
            "action": {
                "type": "Tap",
                "param": {"locate": {"prompt": "the button"}},
            }
        },
        {"finalize_success": True, "finalize_message": "done"},
    ]

    async def fake_plan_once(*args, **kwargs):
        return plans.pop(0)

    monkeypatch.setattr(agent, "_plan_once", fake_plan_once)
    assert await agent.ai_action("tap the button") == "done"

    # A planner without planning-cache support disables locate caching and
    # plan-cache writes for the whole aiAct (upstream #3418).
    assert interface.resolved == []
    assert interface.features == []
    assert len(cache.cache["caches"]) == 2  # only the seeded entries


@pytest.mark.asyncio
async def test_should_not_call_ai_locate_when_bbox_is_available(tmp_path, monkeypatch):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    interface = _CacheInterface()
    agent = Agent(interface, AgentOptions(cache_id="locate-plan-priority"))
    agent._get_task_cache().append_locate_cache("the button", {"xpaths": ["/cached"]})

    async def fail_locate(*args, **kwargs):
        raise AssertionError("AI locate must not run on a plan hit")

    monkeypatch.setattr(agent, "_run_locate", fail_locate)
    result = await agent._locate_for_action(
        {
            "prompt": "the button",
            "locatedPixelResult": {"center": [7, 8]},
        }
    )

    assert result == {"center": [7, 8]}
    assert interface.resolved == []
    assert interface.features == []
    assert len(agent._get_task_cache().cache["caches"]) == 1


@pytest.mark.asyncio
async def test_should_handle_cache_feature_for_point_returning_empty_object(
    tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    class EmptyFeatureInterface(_CacheInterface):
        async def cache_feature_for_point(self, center, options=None):
            self.features.append(list(center))
            return {"xpaths": []}

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    agent = Agent(EmptyFeatureInterface(), AgentOptions(cache_id="locate-empty"))

    async def fake_locate(*args, **kwargs):
        return {"center": [1, 2], "rect": None}

    monkeypatch.setattr(agent, "_run_locate", fake_locate)
    await agent._locate_for_action({"prompt": "the button"})

    assert agent._get_task_cache().cache["caches"] == []


@pytest.mark.asyncio
async def test_cached_plan_replay_drops_stale_pixels():
    from midscene.core.agent.agent import Agent

    agent = Agent(MockInterface())
    captured = []

    async def fake_execute(action):
        captured.append(action)

    agent._execute_planning_action = fake_execute
    yaml_workflow = (
        "tasks:\n"
        "  - name: t\n"
        "    flow:\n"
        "      - type: Tap\n"
        "        locate:\n"
        "          prompt: the button\n"
        "          locatedPixelResult:\n"
        "            center: [1, 2]\n"
    )

    assert await agent._replay_cached_plan({"yamlWorkflow": yaml_workflow})
    assert captured[0]["param"]["locate"] == {"prompt": "the button"}
