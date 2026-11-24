"""CLI report sessions (upstream cli-report-session.test.ts)."""

import json
import re
from pathlib import Path

import pytest

from midscene.shared.agent_tools.base_tools import BaseMidsceneTools
from midscene.shared.agent_tools.types import ToolDefinition, ToolResult
from midscene.shared.env import get_midscene_run_dir


class _FakeDevice:
    def action_space(self):
        return []


class _FakePage:
    async def screenshot_base64(self):
        return "data:image/png;base64,Zm9v"


class _FakeAgent:
    def __init__(self, ai_action, ai_assert):
        self._ai_action = ai_action
        self._ai_assert = ai_assert
        self.page = _FakePage()

    async def get_action_space(self):
        return []

    async def ai_action(self, prompt, options=None):
        self._ai_action.append((prompt, options))

    async def ai_assert(self, prompt, message=None):
        self._ai_assert.append((prompt, message))


class FakeCliTools(BaseMidsceneTools):
    def __init__(self, fail_ensure_agent: bool = False):
        super().__init__()
        self.fail_ensure_agent = fail_ensure_agent
        self.created_report_file_names = []
        self.created_report_group_ids = []
        self.ai_action_calls = []
        self.ai_assert_calls = []

    def get_cli_report_session_name(self):
        return "midscene-test"

    def create_temporary_device(self):
        return _FakeDevice()

    async def ensure_agent(self, init_param=None):
        report_options = self.read_cli_report_agent_options()
        self.created_report_file_names.append(
            report_options.get("reportFileName") if report_options else None
        )
        self.created_report_group_ids.append(
            report_options["reportAttributes"]["data-group-id"]
            if report_options
            else None
        )
        if self.fail_ensure_agent:
            raise RuntimeError("connect failed")
        return _FakeAgent(self.ai_action_calls, self.ai_assert_calls)

    def prepare_platform_tools(self):
        async def handler(_args):
            report_session = self.create_new_cli_report_session("test-device")
            self.commit_cli_report_session(report_session)
            await self.ensure_agent()
            return ToolResult([{"type": "text", "text": "connected"}])

        return [
            ToolDefinition(
                name="test_connect",
                description="Connect test device",
                schema={"url": {"type": "string", "optional": True}},
                handler=handler,
            )
        ]


def _session_path() -> Path:
    return Path(get_midscene_run_dir("cli-report-session")) / "midscene-test.json"


class TestCliReportSession:
    @pytest.mark.asyncio
    async def test_records_a_new_report_file_on_connect_and_reuses_it_for_later_lazy_agent_commands(
        self,
    ):
        connect_tools = FakeCliTools()
        await connect_tools.init_tools()
        connect_tool = next(
            tool
            for tool in connect_tools.get_tool_definitions()
            if tool.name == "test_connect"
        )

        await connect_tool.handler({})

        first_report_file_name = connect_tools.created_report_file_names[0]
        assert re.match(r"^midscene-test-test-device-", first_report_file_name)

        session = json.loads(_session_path().read_text(encoding="utf-8"))
        assert session["reportFileName"] == first_report_file_name
        assert (
            str(Path("midscene_run", "report", f"{first_report_file_name}.html"))
            in session["reportPath"]
        )

        action_tools = FakeCliTools()
        await action_tools.init_tools()
        act_tool = next(
            tool for tool in action_tools.get_tool_definitions() if tool.name == "act"
        )

        await act_tool.handler({"prompt": "click the button"})

        assert action_tools.created_report_file_names == [first_report_file_name]
        assert action_tools.created_report_group_ids == [first_report_file_name]
        assert action_tools.ai_action_calls == [
            ("click the button", {"deepThink": False})
        ]

    @pytest.mark.asyncio
    async def test_reuses_report_session_for_assert_with_a_realistic_ui_verification_prompt(
        self,
    ):
        connect_tools = FakeCliTools()
        await connect_tools.init_tools()
        connect_tool = next(
            tool
            for tool in connect_tools.get_tool_definitions()
            if tool.name == "test_connect"
        )
        await connect_tool.handler({})

        first_report_file_name = connect_tools.created_report_file_names[0]

        assert_tools = FakeCliTools()
        await assert_tools.init_tools()
        assert_tool = next(
            tool
            for tool in assert_tools.get_tool_definitions()
            if tool.name == "assert"
        )

        await assert_tool.handler(
            {"prompt": "The login page shows both email and password input fields"}
        )

        assert assert_tools.created_report_file_names == [first_report_file_name]
        assert assert_tools.created_report_group_ids == [first_report_file_name]
        assert assert_tools.ai_assert_calls == [
            (
                "The login page shows both email and password input fields",
                None,
            )
        ]

    @pytest.mark.asyncio
    async def test_creates_a_different_report_file_for_each_connect_call(self):
        first_tools = FakeCliTools()
        await first_tools.init_tools()
        await next(
            tool
            for tool in first_tools.get_tool_definitions()
            if tool.name == "test_connect"
        ).handler({})

        second_tools = FakeCliTools()
        await second_tools.init_tools()
        await next(
            tool
            for tool in second_tools.get_tool_definitions()
            if tool.name == "test_connect"
        ).handler({})

        assert first_tools.created_report_file_names[0] is not None
        assert second_tools.created_report_file_names[0] is not None
        assert (
            second_tools.created_report_file_names[0]
            != first_tools.created_report_file_names[0]
        )

    @pytest.mark.asyncio
    async def test_refreshes_the_report_file_even_when_connect_fails_to_create_an_agent(
        self,
    ):
        failing_tools = FakeCliTools(True)
        await failing_tools.init_tools()
        connect_tool = next(
            tool
            for tool in failing_tools.get_tool_definitions()
            if tool.name == "test_connect"
        )

        with pytest.raises(RuntimeError, match="connect failed"):
            await connect_tool.handler({})

        session = json.loads(_session_path().read_text(encoding="utf-8"))
        assert re.match(r"^midscene-test-test-device-", session["reportFileName"])
        assert failing_tools.created_report_file_names == [session["reportFileName"]]
        assert failing_tools.created_report_group_ids == [session["reportFileName"]]
