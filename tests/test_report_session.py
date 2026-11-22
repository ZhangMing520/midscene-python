"""Synced from upstream ``packages/core/tests/unit-test/report-session.test.ts``."""

import asyncio
import json

import pytest


def _agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config))


class TestTestOwnedReportRecords:
    def test_records_without_publishing_agent_html(self, tmp_path, monkeypatch):
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
    async def test_releases_finished_writers_immediately_while_preserving_uncollected_diagnostics_until_session_finish(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _agent()
        agent.record_to_report("note", {"content": "x"})
        await agent.destroy()
        assert list((tmp_path / "report").glob("*.json"))
