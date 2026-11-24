"""Synced from upstream
``packages/core/tests/unit-test/legacy-yaml-executable-contract.test.ts``
(case ``recordToReport-report-record``)."""

import asyncio

from midscene.core.yaml import ScriptPlayer, parse_yaml_script


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


def test_record_to_report_report_record(tmp_path, monkeypatch):
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
