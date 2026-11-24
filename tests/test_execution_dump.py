"""Synced from upstream packages/core/tests/unit-test/execution-dump.test.ts and
agent-report-*.test.ts."""

import base64
import json
import re
from unittest.mock import AsyncMock, patch

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


def _read_report(tmp_path):
    files = sorted((tmp_path / "report").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_should_serialize_execution_dump_on_success(
    mock_interface, tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    responses = [
        (
            "<action-type>Tap</action-type>\n"
            "<action-param-json>\n"
            '{"locate": {"prompt": "the button", '
            '"bbox": [190, 115, 210, 135], '
            '"locatedPixelResult": {"center": [200, 125]}}}\n'
            "</action-param-json>"
        ),
        '<complete success="true">finished</complete>',
    ]
    calls = {"n": 0}

    async def planning_handler(*args, **kwargs):
        calls["n"] += 1
        return {"content": responses[calls["n"] - 1], "usage": None}

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config=dict(MODEL_CONFIG),
                persist_execution_dump=True,
            ),
        )
        assert await agent.ai_action("tap the test button") == "finished"

    path, dump = _read_report(tmp_path)
    assert re.match(
        r"^web-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-[0-9a-f]{8}\.json$",
        path.name,
    )
    assert dump["deviceType"] == "web"
    execution = dump["executions"][0]
    assert execution["name"] == "tap the test button"

    planning, action = execution["tasks"]
    assert planning["type"] == "Planning"
    assert planning["status"] == "finished"
    assert planning["output"] == "finished"
    assert "cache" not in planning  # not an upstream field
    assert action["type"] == "Action Space"
    assert action["subType"] == "Tap"
    assert action["status"] == "finished"
    assert "errorMessage" not in action
    # The plan carried locatedPixelResult; the dump must drop it so a
    # cached replay can never click stale screenshot coordinates.
    assert action["param"]["locate"] == {"prompt": "the button"}
    assert action["timing"]["cost"] >= 0
    # Report timestamps are wall-clock epoch ms, like upstream Date.now().
    assert abs(action["timing"]["start"] - planning["logTime"]) < 60_000


@pytest.mark.asyncio
async def test_should_serialize_the_bounded_task_error_created_by_task_runner(
    mock_interface, tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {
            "content": '<complete success="false">could not find it</complete>',
            "usage": None,
        },
    ):
        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config=dict(MODEL_CONFIG),
                persist_execution_dump=True,
            ),
        )
        with pytest.raises(AssertionError):
            await agent.ai_action("do the impossible")

    _, dump = _read_report(tmp_path)
    tasks = dump["executions"][0]["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["type"] == "Planning"
    assert tasks[0]["status"] == "failed"
    assert tasks[0]["output"] is None
    assert "could not find it" in tasks[0]["errorMessage"]


@pytest.mark.asyncio
async def test_cached_replay_report_marks_cache_hit(
    mock_interface, tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    yaml_workflow = (
        "tasks:\n  - name: t\n    flow:\n      - type: Sleep\n        timeMs: 1\n"
    )
    agent = Agent(
        mock_interface,
        AgentOptions(
            cache_id="report-replay",
            model_config=dict(MODEL_CONFIG),
            persist_execution_dump=True,
        ),
    )
    agent._get_task_cache().append_plan_cache("cached prompt", yaml_workflow)

    async def fake_execute(action):
        return None

    monkeypatch.setattr(agent, "_execute_planning_action", fake_execute)

    async def fail_planning(*args, **kwargs):
        raise AssertionError("planning must not run on a cache replay")

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        fail_planning,
    ):
        assert await agent.ai_action("cached prompt") is None

    _, dump = _read_report(tmp_path)
    planning, action = dump["executions"][0]["tasks"]
    assert planning["status"] == "finished"
    assert planning["subType"] == "LoadYaml"
    assert "cache" not in planning
    assert planning["hitBy"]["from"] == "Cache"
    assert planning["hitBy"]["context"]["yamlString"] == yaml_workflow
    assert planning["output"]["yamlString"] == yaml_workflow
    assert planning["output"]["shouldContinuePlanning"] is False
    assert action["subType"] == "Sleep"
    assert action["status"] == "finished"


def test_report_file_name_format_and_env_tag(monkeypatch):
    from midscene.core.dump import get_report_file_name

    monkeypatch.delenv("MIDSCENE_REPORT_TAG_NAME", raising=False)
    assert re.match(
        r"^android-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-[0-9a-f]{8}$",
        get_report_file_name("android"),
    )

    monkeypatch.setenv("MIDSCENE_REPORT_TAG_NAME", "my-suite")
    assert get_report_file_name("web").startswith("my-suite-")


@pytest.mark.asyncio
async def test_generate_report_false_writes_no_dump(
    mock_interface, tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {
            "content": '<complete success="true">done</complete>',
            "usage": None,
        },
    ):
        agent = Agent(
            mock_interface,
            AgentOptions(model_config=dict(MODEL_CONFIG), generate_report=False),
        )
        assert await agent.ai_action("no report") == "done"

    assert list((tmp_path / "report").glob("*.json")) == []


@pytest.mark.asyncio
async def test_preserves_report_file_name_and_group_metadata(
    mock_interface, tmp_path, monkeypatch
):
    from midscene.core.agent.agent import Agent

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {
            "content": '<complete success="true">done</complete>',
            "usage": None,
        },
    ):
        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config=dict(MODEL_CONFIG),
                report_file_name="suite-report.html",
                group_name="My Suite",
                group_description="Regression run",
                persist_execution_dump=True,
            ),
        )
        assert await agent.ai_action("custom report") == "done"

    path, dump = _read_report(tmp_path)
    assert path.name == "suite-report.json"
    assert dump["groupName"] == "My Suite"
    assert dump["groupDescription"] == "Regression run"


class TestDump:
    def test_report_dump_structure(self):
        from midscene.core.dump import (
            ExecutionDumpBuilder,
            build_execution_task,
            build_service_dump,
        )

        builder = ExecutionDumpBuilder(group_name="g", device_type="web")
        service_dump = build_service_dump(
            "locate",
            {"element": "the button"},
            None,
            {"durationMs": 12, "rawResponse": "r", "usage": {"total_tokens": 5}},
            matched_element=[{"center": [1, 2]}],
            deep_locate=True,
        )
        task = build_execution_task(
            "Insight", "Locate", {"prompt": "the button"}, log=service_dump
        )
        builder.add_execution("Tap - the button", [task])
        dump = builder.to_dict()

        assert dump["sdkVersion"]
        assert dump["groupName"] == "g"
        assert dump["deviceType"] == "web"
        execution = dump["executions"][0]
        assert execution["name"] == "Tap - the button"
        assert execution["tasks"][0]["type"] == "Insight"
        assert execution["tasks"][0]["subType"] == "Locate"
        assert execution["tasks"][0]["log"]["type"] == "locate"
        assert execution["tasks"][0]["log"]["deepLocate"] is True

    def test_dump_writes_to_disk(self, tmp_path, monkeypatch):
        from midscene.core.dump import ExecutionDumpBuilder, build_execution_task

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        builder = ExecutionDumpBuilder(group_name="g")
        builder.add_execution(
            "Sleep", [build_execution_task("Action Space", "Sleep", {"timeMs": 1})]
        )
        path = builder.write_to_disk("unit-dump")
        assert path
        content = json.loads(open(path).read())
        assert content["executions"][0]["tasks"][0]["subType"] == "Sleep"
