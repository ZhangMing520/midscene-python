"""Synced from upstream packages/core/tests/unit-test/agent*.test.ts suites."""

import base64
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.agent.agent_options import AgentOptions
from midscene.core.types import (
    BaseElement,
    NodeType,
    Rect,
    ScrollParam,
    Size,
    UIContext,
    UINode,
    UITree,
)


def make_png_base64(width: int = 320, height: int = 240) -> str:
    from PIL import Image
    import io

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
        self.tapped: List[tuple] = []
        self.typed: List[str] = []
        self.keys: List[str] = []
        self.scrolled: List[tuple] = []

    async def get_context(self) -> UIContext:
        if self._context:
            return self._context
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


@pytest.fixture
def mock_interface():
    return MockInterface()


MODEL_CONFIG = {
    "MIDSCENE_MODEL_NAME": "mock-model",
    "MIDSCENE_MODEL_API_KEY": "sk-test",
    "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
    "MIDSCENE_MODEL_FAMILY": "gpt-5",
}


def patch_model_call(module_path: str, handler):
    target = f"{module_path}.call_generative_ai"
    return patch(target, new=AsyncMock(side_effect=handler))


@pytest.mark.asyncio
async def test_agent_creation(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(mock_interface)

    assert agent.interface == mock_interface
    assert agent.destroyed is False
    assert [a.name for a in agent.action_space][0] == "Tap"


@pytest.mark.asyncio
async def test_basic_actions(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(mock_interface)
    await agent.tap(100, 200)
    await agent.input_text("test text")
    await agent.scroll(
        ScrollParam(direction="down", scroll_type="once", distance=500)
    )

    assert mock_interface.tapped == [(100, 200)]
    assert mock_interface.typed == ["test text"]
    assert mock_interface.scrolled[0][0] == "down"


@pytest.mark.asyncio
async def test_agent_destroy(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(mock_interface)
    await agent.destroy()

    assert agent.destroyed is True
    with pytest.raises(RuntimeError):
        await agent.ai_locate("test")


@pytest.mark.asyncio
async def test_ai_action_full_loop(mock_interface):
    """Plan -> execute Tap -> complete; interface receives the tap."""
    from midscene.core.agent.agent import Agent

    responses = [
        (
            "<planning>tap</planning>\n"
            "<log>Tap the button</log>\n"
            "<action-type>Tap</action-type>\n"
            "<action-param-json>\n"
            '{"locate": {"prompt": "the test button", '
            '"bbox": [190, 115, 210, 135]}}\n'
            "</action-param-json>"
        ),
        '<complete success="true">finished</complete>',
    ]
    planning_calls = {"n": 0}
    locate_calls = {"n": 0}

    async def planning_handler(*args, **kwargs):
        planning_calls["n"] += 1
        return {
            "content": responses[planning_calls["n"] - 1],
            "usage": {"total_tokens": 7},
        }

    async def locate_handler(*args, **kwargs):
        locate_calls["n"] += 1
        return {
            "content": '{"bbox": [190, 115, 210, 135]}',
            "usage": {"total_tokens": 3},
        }

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ), patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate", locate_handler
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        result = await agent.ai_action("tap the test button")

    assert result == "finished"  # finalize message from <complete>
    assert mock_interface.tapped == [(200, 125)]
    assert planning_calls["n"] == 2
    # Planning included pixel coordinates, so locate is not called again.
    assert locate_calls["n"] == 0


@pytest.mark.asyncio
async def test_ai_action_complete_false_raises(mock_interface):
    from midscene.core.agent.agent import Agent

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {
            "content": '<complete success="false">could not find it</complete>',
            "usage": None,
        },
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        with pytest.raises(AssertionError) as exc:
            await agent.ai_action("do the impossible")

    assert "could not find it" in str(exc.value)


@pytest.mark.asyncio
async def test_ai_act_passes_context_to_planning(mock_interface):
    from midscene.core.agent.agent import Agent

    prompts: List[str] = []

    async def planning_handler(messages, *args, **kwargs):
        prompts.append(str(messages))
        return {
            "content": '<complete success="true">done</complete>',
            "usage": None,
        }

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        result = await agent.ai_act(
            "do it", {"context": "PREMIUM-ACCOUNT-CONTEXT"}
        )

    assert result == "done"
    assert prompts
    assert "PREMIUM-ACCOUNT-CONTEXT" in prompts[0]


@pytest.mark.asyncio
async def test_ai_action_retries_after_execution_error(mock_interface):
    """A failed locate does not abort the task; agent reports error feedback
    to the planner and continues."""
    from midscene.core.agent.agent import Agent

    responses = [
        (
            "<action-type>Tap</action-type>\n"
            "<action-param-json>\n"
            '{"locate": {"prompt": "missing element"}}\n'
            "</action-param-json>"
        ),
        '<complete success="true">done</complete>',
    ]
    planning_calls = {"n": 0}

    async def planning_handler(*args, **kwargs):
        planning_calls["n"] += 1
        return {"content": responses[planning_calls["n"] - 1], "usage": None}

    async def locate_handler(*args, **kwargs):
        return {
            "content": '{"bbox": [], "error": "element not found"}',
            "usage": None,
        }

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ), patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate", locate_handler
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        result = await agent.ai_action("retry flow")

    assert result == "done"
    assert planning_calls["n"] == 2
    assert mock_interface.tapped == []


@pytest.mark.asyncio
async def test_ai_locate(mock_interface):
    from midscene.core.agent.agent import Agent

    with patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate",
        lambda *a, **k: {
            "content": '{"bbox": [190, 115, 210, 135]}',
            "usage": None,
            "raw_response": "raw",
        },
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        result = await agent.ai_locate("the test button")

    assert list(result.center) == [200, 125]
    assert result.rect.left == 190


@pytest.mark.asyncio
async def test_ai_input_legacy_signature(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(mock_interface)
    calls = []

    async def fake_call(action_type, param=None):
        calls.append((action_type, param))

    agent._call_action_in_action_space = fake_call
    await agent.ai_input("hello", "the search box")

    assert calls == [
        ("Input", {"value": "hello", "locate": {"prompt": "the search box"}})
    ]


@pytest.mark.asyncio
async def test_ai_extract(mock_interface):
    from midscene.core.agent.agent import Agent

    raw = '<data-json>{"username": "testuser"}</data-json>'
    with patch_model_call(
        "midscene.core.ai_model.workflows.insight.extraction",
        lambda *a, **k: {"content": raw, "usage": None},
    ):
        agent = Agent(
            mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG))
        )
        result = await agent.ai_extract("extract username")

    assert result == {"username": "testuser"}


@pytest.mark.asyncio
async def test_ai_assert_success_and_failure(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(mock_interface, AgentOptions(model_config=dict(MODEL_CONFIG)))

    with patch_model_call(
        "midscene.core.ai_model.workflows.insight.extraction",
        lambda *a, **k: {
            "content": '<data-json>{"StatementIsTruthy": true}</data-json>',
            "usage": None,
        },
    ):
        await agent.ai_assert("page is loaded")

    with patch_model_call(
        "midscene.core.ai_model.workflows.insight.extraction",
        lambda *a, **k: {
            "content": '<data-json>{"StatementIsTruthy": false}</data-json>',
            "usage": None,
        },
    ):
        with pytest.raises(AssertionError):
            await agent.ai_assert("user is logged in")


@pytest.mark.asyncio
async def test_model_config_dict(mock_interface):
    from midscene.core.agent.agent import Agent

    agent = Agent(
        mock_interface,
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "m1",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
            }
        ),
    )

    config = agent.model_runtime("default").config
    assert config["modelName"] == "m1"


@pytest.mark.asyncio
async def test_plan_cache_replay(mock_interface, tmp_path, monkeypatch):
    """Second ai_action with the same prompt replays the cached plan."""
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))

    planning_calls = {"n": 0}
    responses = [
        (
            "<action-type>Sleep</action-type>\n"
            "<action-param-json>\n"
            '{"timeMs": 1}\n'
            "</action-param-json>"
        ),
        '<complete success="true">done</complete>',
    ]

    async def planning_handler(*args, **kwargs):
        planning_calls["n"] += 1
        return {"content": responses[min(planning_calls["n"], 2) - 1], "usage": None}

    model_config = dict(MODEL_CONFIG)
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        agent = Agent(
            mock_interface,
            AgentOptions(cache_id="cache-test", model_config=model_config),
        )
        await agent.ai_action("run the cached flow")
    assert planning_calls["n"] == 2

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        agent2 = Agent(
            mock_interface,
            AgentOptions(cache_id="cache-test", model_config=model_config),
        )
        result = await agent2.ai_action("run the cached flow")

    assert planning_calls["n"] == 2  # no new planning calls
    assert result is None  # replay produces no finalize message

    # cleanup cache file
    agent2._task_cache.flush()
