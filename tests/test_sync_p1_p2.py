"""
Tests for the P1/P2 sync batch (SYNC_TODO.md):
screenshot shrink, ADB input strategy, RunAdbShell/Launch/Terminate,
domIncluded, cache strategy, Pinch, recordToReport, agent options.
"""

import asyncio
import base64
import io
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tests.test_core import MockInterface, make_png_base64


@pytest.fixture
def mock_interface():
    return MockInterface()


def _agent(model_family: str = "gpt-5", **options):
    from midscene.core.agent import Agent
    from midscene.core.types import AgentOptions

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": model_family,
    }
    return Agent(
        MockInterface(), AgentOptions(model_config=config, **options)
    )


# ---------------------------------------------------------------------------
# P1-1 screenshot shrink
# ---------------------------------------------------------------------------


class TestScreenshotShrink:
    def _image_size(self, base64_str: str):
        from PIL import Image

        raw = base64_str.split(",", 1)[1] if base64_str.startswith("data:") else base64_str
        return Image.open(io.BytesIO(base64.b64decode(raw))).size

    def test_shrink_halves_screenshot_and_sets_ratio(self):
        from midscene.core.types import UIContext, Size, UITree, UINode, Rect, NodeType

        context = UIContext(
            screenshot_base64=make_png_base64(320, 240),
            size=Size(width=160, height=120),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root", content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0), node_type=NodeType.CONTAINER,
                )
            ),
        )
        agent = _agent(screenshot_shrink_factor=2.0)
        shrunk = agent._apply_screenshot_shrink(context)
        assert self._image_size(shrunk.screenshot_base64) == (160, 120)
        # dpr = 320/160 = 2; ratio = dpr / factor = 1
        assert shrunk.shrunk_shot_to_logical_ratio == pytest.approx(1.0)

    def test_no_shrink_when_factor_one(self):
        from midscene.core.types import UIContext, Size, UITree, UINode, Rect, NodeType

        context = UIContext(
            screenshot_base64=make_png_base64(320, 240),
            size=Size(width=160, height=120),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root", content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0), node_type=NodeType.CONTAINER,
                )
            ),
        )
        agent = _agent()
        shrunk = agent._apply_screenshot_shrink(context)
        assert shrunk.screenshot_base64 == context.screenshot_base64
        assert shrunk.shrunk_shot_to_logical_ratio == 1.0

    def test_locate_result_scaled_to_logical(self):
        from midscene.core.types import UIContext, Size, UITree, UINode, Rect, NodeType

        agent = _agent()
        context = UIContext(
            screenshot_base64=make_png_base64(),
            size=Size(width=320, height=240),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root", content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0), node_type=NodeType.CONTAINER,
                )
            ),
            shrunk_shot_to_logical_ratio=2.0,
        )
        element = {"center": (50, 60), "rect": {"left": 40, "top": 50, "width": 20, "height": 20}}
        scaled = agent._to_logical_coords(element, context)
        assert scaled["center"] == [100, 120]
        assert scaled["rect"]["left"] == 80

    @pytest.mark.asyncio
    async def test_ai_act_passes_shrunk_context_to_planning(self):
        """get_ui_context applies shrink when the option is set."""
        agent = _agent(screenshot_shrink_factor=2.0)
        context = await agent.get_ui_context("locate")
        # logical 160x120 from MockInterface(320x240 png, size 320x240):
        # physical 320 == logical 320 -> dpr 1 -> ratio 0.5, image halved
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(0.5)
        width, height = self._image_size(context.screenshot_base64)
        assert (width, height) == (160, 120)


# ---------------------------------------------------------------------------
# P1-2 ADB input
# ---------------------------------------------------------------------------


class TestAdbInput:
    def test_escape_for_shell(self):
        from midscene.android.device import escape_for_shell, shell_escape_arg

        assert escape_for_shell("it's") == "it'\\''s"
        assert escape_for_shell("a\nb") == "a\\nb"
        assert shell_escape_arg("a b&c") == "'a b&c'"
        assert shell_escape_arg("it's") == "'it'\\''s'"

    def test_should_use_yadb_for_text(self):
        from midscene.android.device import should_use_yadb_for_text

        assert should_use_yadb_for_text("中文输入") is True
        assert should_use_yadb_for_text("café") is True
        # upstream regex /%[a-zA-Z]/: only %-immediately-followed-by-letter
        assert should_use_yadb_for_text("%s") is True
        assert should_use_yadb_for_text("50% off") is False
        assert should_use_yadb_for_text("back\\slash") is True
        assert should_use_yadb_for_text("a\"b'c") is True
        assert should_use_yadb_for_text("plain text 123") is False

    @pytest.mark.asyncio
    async def test_legacy_strategy_uses_escaped_input_text(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        monkeypatch.setenv("MIDSCENE_ANDROID_IME_STRATEGY", "legacy")
        device = AndroidDevice("emulator-5554")
        device._connected = True
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        await device.input_text("hello world")
        assert commands == [
            ["-s", "emulator-5554", "shell", "input", "text", "'hello world'"]
        ]

    @pytest.mark.asyncio
    async def test_non_ascii_routes_through_yadb(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("emulator-5554")
        device._connected = True
        calls: List[str] = []

        async def fake_exec(content):
            calls.append(content)

        device._exec_yadb_raw = fake_exec
        await device.input_text("你好 world")
        # escape_for_shell applied; Chinese text triggers yadb
        assert calls == ["你好 world"]

    @pytest.mark.asyncio
    async def test_yadb_failure_falls_back_to_input_text(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("emulator-5554")
        device._connected = True
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        async def fail_ensure():
            raise RuntimeError("download failed")

        device._run_adb_command = fake_run
        device._ensure_yadb = fail_ensure
        await device.input_text("你好")
        assert commands and commands[0][3:5] == ["input", "text"]

    @pytest.mark.asyncio
    async def test_newline_splits_with_enter(self, monkeypatch):
        from midscene.android.device import AndroidDevice

        monkeypatch.setenv("MIDSCENE_ANDROID_IME_STRATEGY", "legacy")
        device = AndroidDevice("emulator-5554")
        device._connected = True
        commands: List[list] = []

        async def fake_run(cmd):
            commands.append(cmd)
            return ""

        device._run_adb_command = fake_run
        await device.input_text("a\nb")
        assert commands[0][-1] == "'a'"
        assert "KEYCODE_ENTER" in commands[1]
        assert commands[2][-1] == "'b'"


# ---------------------------------------------------------------------------
# P1-2/P1-5 RunAdbShell / Launch / Terminate actions
# ---------------------------------------------------------------------------


class TestAndroidActions:
    def test_actions_registered(self):
        from midscene.core.actions import build_android_action_space

        names = [a.name for a in build_android_action_space()]
        assert {"RunAdbShell", "Launch", "Terminate"} <= set(names)

    @pytest.mark.asyncio
    async def test_run_adb_shell_executor(self):
        from midscene.core.actions import build_android_action_space, find_action_in_action_space_or_throw

        executed: List[str] = []

        class Device:
            async def run_adb_shell(self, command, timeout=None):
                executed.append((command, timeout))

        definition = find_action_in_action_space_or_throw(
            "RunAdbShell", build_android_action_space()
        )
        await definition.execute({"command": "ls", "timeout": 1000}, Device(), None)
        assert executed == [("ls", 1000.0)]

    @pytest.mark.asyncio
    async def test_launch_and_terminate_executors(self):
        from midscene.core.actions import build_android_action_space, find_action_in_action_space_or_throw

        calls: List[tuple] = []

        class Device:
            async def launch_app(self, uri):
                calls.append(("launch", uri))

            async def stop_app(self, uri):
                calls.append(("terminate", uri))

        space = build_android_action_space()
        await find_action_in_action_space_or_throw("Launch", space).execute(
            {"uri": "com.a.b"}, Device(), None
        )
        await find_action_in_action_space_or_throw("Terminate", space).execute(
            {"uri": "com.a.b"}, Device(), None
        )
        assert calls == [("launch", "com.a.b"), ("terminate", "com.a.b")]

    @pytest.mark.asyncio
    async def test_launch_requires_uri(self):
        from midscene.core.actions import build_android_action_space, find_action_in_action_space_or_throw

        space = build_android_action_space()
        with pytest.raises(ValueError):
            await find_action_in_action_space_or_throw("Launch", space).execute(
                {}, Mock(), None
            )


# ---------------------------------------------------------------------------
# P1-3 domIncluded
# ---------------------------------------------------------------------------


class TestDomIncluded:
    def test_render_ai_context(self, mock_interface):
        from midscene.core.ai_model.workflows.context_utils import render_ai_context

        import asyncio

        context = asyncio.run(mock_interface.get_context())
        rendered = render_ai_context(context)
        assert rendered is not None
        assert "id=test_element" in rendered
        assert "Test Button" in rendered

    def test_render_ai_context_empty(self):
        from midscene.core.ai_model.workflows.context_utils import render_ai_context

        assert render_ai_context(Mock(content=[])) is None

    def test_merge_call_context(self, mock_interface):
        agent = _agent()
        agent.set_ai_context("aiQuery", "base context")

        import asyncio

        context = asyncio.run(mock_interface.get_context())
        merged = agent._merge_call_context("aiQuery", {}, context, dom_included=True)
        assert "base context" in merged
        assert "Page element context" in merged

        only_base = agent._merge_call_context("aiQuery", {}, context, dom_included=False)
        assert only_base == "base context"

    @pytest.mark.asyncio
    async def test_dom_included_reaches_prompt(self, mock_interface):
        captured: Dict[str, Any] = {}

        async def fake_extract(**kwargs):
            captured.update(kwargs)
            return {
                "parse_result": {"data": {"aiQuery": "x"}},
                "usage": None,
            }

        agent = _agent()
        with patch(
            "midscene.core.agent.ai_extract_element_info", new=AsyncMock(side_effect=fake_extract)
        ):
            await agent.ai_query("the title", {"domIncluded": True})
        assert "Page element context" in captured["context_text"]


# ---------------------------------------------------------------------------
# P1-4 cache strategy
# ---------------------------------------------------------------------------


class TestCacheStrategy:
    def _make_agent(self, cache):
        return _agent(cache=cache)

    def test_strategy_read_only(self, tmp_path):
        agent = self._make_agent(
            {"id": "c1", "strategy": "read-only", "cacheDir": str(tmp_path)}
        )
        cache = agent._get_task_cache()
        assert cache.read_only_mode is True and cache.write_only_mode is False
        assert str(tmp_path) in cache.cache_file_path

    def test_strategy_write_only(self):
        agent = self._make_agent({"id": "c2", "strategy": "write-only"})
        cache = agent._get_task_cache()
        assert cache.write_only_mode is True

    def test_invalid_strategy_raises(self):
        agent = self._make_agent({"id": "c3", "strategy": "sometimes"})
        with pytest.raises(ValueError):
            agent._get_task_cache()

    def test_cache_false_disables(self):
        agent = self._make_agent(False)
        assert agent._get_task_cache() is None

    def test_string_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = self._make_agent("my-cache")
        cache = agent._get_task_cache()
        assert cache.cache_id == "my-cache"

    def test_read_only_does_not_write(self, tmp_path):
        agent = self._make_agent(
            {"id": "ro", "strategy": "read-only", "cacheDir": str(tmp_path)}
        )
        cache = agent._get_task_cache()
        cache.append_plan_cache("p", "- type: Tap")
        assert not list(tmp_path.rglob("*.cache.yaml"))


# ---------------------------------------------------------------------------
# P2-1 Pinch
# ---------------------------------------------------------------------------


class TestPinch:
    def test_pinch_in_web_space_only(self):
        from midscene.core.actions import build_web_action_space

        assert "Pinch" in [a.name for a in build_web_action_space()]

    def test_playwright_implements_pinch(self):
        from midscene.web.playwright_page import PlaywrightWebPage

        assert hasattr(PlaywrightWebPage, "pinch")

    def test_android_pinch_not_supported(self):
        from midscene.core.types import AbstractInterface

        assert not hasattr(AbstractInterface, "pinch") or getattr(
            __import__("midscene.android.device", fromlist=["AndroidDevice"]).AndroidDevice,
            "pinch",
            None,
        ) is None

    @pytest.mark.asyncio
    async def test_pinch_executor_validates_direction(self):
        from midscene.core.actions import build_web_action_space, find_action_in_action_space_or_throw

        definition = find_action_in_action_space_or_throw("Pinch", build_web_action_space())
        with pytest.raises(ValueError):
            await definition.execute({"direction": "sideways"}, Mock(), None)

    @pytest.mark.asyncio
    async def test_ai_pinch_param_assembly(self):
        agent = _agent()
        calls: List[tuple] = []

        async def fake_call(action_type, param):
            calls.append((action_type, param))

        with patch.object(agent, "_call_action_in_action_space", new=fake_call):
            await agent.ai_pinch("the map", {"direction": "out", "distance": 120})
        assert calls == [
            (
                "Pinch",
                {
                    "direction": "out",
                    "locate": {"prompt": "the map"},
                    "distance": 120,
                },
            )
        ]


# ---------------------------------------------------------------------------
# P2-2 recordToReport
# ---------------------------------------------------------------------------


class TestRecordToReport:
    def test_record_and_flush(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _agent()
        agent.record_to_report("checkpoint", {"content": "reached step 1"})
        agent.record_to_report("screenshot note", {"content": "see image"})

        asyncio.run(agent.flush_report())

        files = list((tmp_path / "report").glob("*.json"))
        assert len(files) == 1
        dump = json.loads(files[0].read_text())
        executions = dump["executions"]
        assert executions[0]["name"] == "Log - checkpoint"
        assert executions[0]["tasks"][0]["type"] == "Log"

    @pytest.mark.asyncio
    async def test_destroy_flushes_report(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _agent()
        agent.record_to_report("note", {"content": "x"})
        await agent.destroy()
        assert list((tmp_path / "report").glob("*.json"))

    def test_yaml_record_to_report(self, tmp_path, monkeypatch):
        from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        script = parse_yaml_script(
            """
tasks:
  - name: t
    flow:
      - recordToReport:
          title: checkpoint
          content: reached
"""
        )
        agent = _agent()
        player = ScriptPlayer(script, agent)
        asyncio.run(player.run())
        assert player.status == "done"
        assert agent._report_builder is not None
        assert agent._report_builder.dump["executions"][0]["name"] == "Log - checkpoint"


# ---------------------------------------------------------------------------
# P2-3 / P2-5 agent options
# ---------------------------------------------------------------------------


class TestAgentOptions:
    @pytest.mark.asyncio
    async def test_wait_after_action_used(self):
        agent = _agent(wait_after_action_ms=0)
        sleeps: List[float] = []

        real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            # must yield, or the readiness task can never run
            await real_sleep(min(seconds, 0.01) if seconds else 0)

        responses = [
            (
                "<action-type>Sleep</action-type>\n<action-param-json>\n"
                '{"timeMs": 1}\n</action-param-json>'
            ),
            '<complete success="true">done</complete>',
        ]
        calls = {"n": 0}

        async def planning_handler(*args, **kwargs):
            calls["n"] += 1
            return {"content": responses[calls["n"] - 1], "usage": {"total_tokens": 3}}

        readiness_calls: List[Dict[str, Any]] = []

        async def readiness(context):
            readiness_calls.append(context)

        with patch("asyncio.sleep", new=fake_sleep), patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ):
            agent.options.wait_for_action_ready = readiness
            await agent.ai_act("run")

        assert readiness_calls and readiness_calls[0]["action"]["name"] == "Sleep"

    def test_ai_contexts_seeded(self):
        agent = _agent(ai_contexts={"aiQuery": "q-context"})
        assert agent.ai_contexts["aiQuery"] == "q-context"

    def test_legacy_ai_action_context(self):

        agent = _agent()
        agent.options.ai_action_context = "legacy ctx"
        agent.ai_contexts = {}
        agent.ai_contexts["aiAct"] = agent.options.ai_action_context
        assert agent._resolve_call_context("aiAct", None) == "legacy ctx"

    def test_on_llm_usage_and_metrics(self):
        usages: List[Dict[str, Any]] = []
        agent = _agent(on_llm_usage=usages.append)
        runtime = agent.model_runtime("planning")
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        runtime.on_usage(usage)
        assert usages == [usage]
        agent._record_usage_metrics("planning", usage)
        assert agent.metrics["planning"]["total_tokens"] == 15

    def test_report_attributes_merged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _agent(report_attributes={"ciJob": "123"})
        builder = agent._get_report_builder()
        builder.add_execution("Sleep", [])
        path = builder.write_to_disk("attrs")
        dump = json.loads(open(path).read())
        assert dump["ciJob"] == "123"

    @pytest.mark.asyncio
    async def test_persist_execution_dump_false_skips_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _agent(persist_execution_dump=False)

        async def planning_handler(*args, **kwargs):
            return {"content": '<complete success="true">done</complete>', "usage": None}

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ):
            await agent.ai_act("run")
        assert not list((tmp_path / "report").glob("*.json"))


from tests.test_core import patch_model_call  # noqa: E402


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
