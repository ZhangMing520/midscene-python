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


class TestReportSession:
    def test_rejects_relative_directories(self):
        from midscene.core.dump.report_session import ReportSession

        with pytest.raises(ValueError, match="absolute"):
            ReportSession("relative/report")

    def test_requires_run_before_creating_a_writer(self, tmp_path):
        from midscene.core.dump.report_session import ReportSession

        session = ReportSession(str(tmp_path / "report"))
        with pytest.raises(RuntimeError, match="Start the report session"):
            session.create_recorder(lambda: False)

    @pytest.mark.asyncio
    async def test_tracks_context_captures_snapshots_and_prunes(self, tmp_path):
        from midscene.core.dump.report_session import (
            ReportSession,
            current_report_session,
        )

        session = ReportSession(str(tmp_path / "report"))

        async def work():
            assert current_report_session() is session
            writer = session.create_recorder(lambda: False)
            writer.on_execution_update(
                {"id": "e1", "name": "first", "tasks": []},
                {"testId": "test-1"},
            )
            source = await writer.create_source_snapshot("scope-1", ["e1"])
            assert source["collection"]["status"] == "complete"
            assert (
                json.loads(open(source["dumpPath"], encoding="utf-8").read())[
                    "executions"
                ][0]["id"]
                == "e1"
            )
            writer.on_execution_update(
                {"id": "e2", "name": "second", "tasks": []},
                {"testId": "test-1"},
            )
            return source

        source = await session.run(work)
        assert source["sourcePath"] == source["dumpPath"]
        assert current_report_session() is None

        remaining = await session.finish()
        assert len(remaining) == 1
        assert remaining[0]["dumpPath"] != source["dumpPath"]
        assert (tmp_path / "report" / "report.json").exists()

        await session.prune()
        assert not (tmp_path / "report" / "report.json").exists()
        assert len(list((tmp_path / "report").glob("*.json"))) == 2
