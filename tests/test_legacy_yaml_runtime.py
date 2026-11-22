"""Synced from upstream ``packages/core/tests/unit-test/legacy-yaml-runtime.test.ts``
(``keeps legacy error reporting and exposes the original action error``)."""

import pytest

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


@pytest.mark.asyncio
async def test_keeps_legacy_error_reporting_and_exposes_the_original_action_error(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    agent = _agent()
    await agent.record_error_to_report(
        "boom", {"error": ValueError("bad state"), "content": "step failed"}
    )

    execution = agent._report_builder.dump["executions"][-1]
    task = execution["tasks"][0]
    assert execution["name"] == "boom"
    assert execution["description"] == "step failed"
    assert task["type"] == "Log"
    assert task["subType"] == "Error"
    assert task["status"] == "failed"
    assert task["errorMessage"] == "bad state"
    assert "ValueError" in task["error"]["name"]
    assert task["output"]


@pytest.mark.asyncio
async def test_reports_yaml_task_failure_through_record_error_to_report(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    script = parse_yaml_script(
        """
tasks:
  - name: t
    flow:
      - aiAct: do something
"""
    )
    agent = _agent()

    async def fail(*args, **kwargs):
        raise RuntimeError("model failed")

    monkeypatch.setattr(agent, "ai_act", fail)
    player = ScriptPlayer(script, agent)
    await player.run()

    assert player.status == "error"
    assert player.failed_tasks[0]["error"] == "model failed"
    names = [
        execution["name"] for execution in agent._report_builder.dump["executions"]
    ]
    assert names == ["YAML task failed - t"]
