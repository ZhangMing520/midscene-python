"""Synced from upstream ``packages/core/tests/unit-test/report-generator.test.ts``
and the report HTML output path."""

import json

import pytest

from tests.core_helpers import patch_model_call


def _agent(**options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config, **options))


def test_should_append_and_override_report_attributes_across_updates(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    agent = _agent(report_attributes={"ciJob": "123"})
    builder = agent._get_report_builder()
    builder.add_execution("Sleep", [])
    path = builder.write_to_disk("attrs")
    dump = json.loads(open(path).read())
    assert dump["ciJob"] == "123"


@pytest.mark.asyncio
async def test_should_skip_persisting_execution_dump_files_when_persist_execution_dump_is_false(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    agent = _agent(persist_execution_dump=False)

    async def planning_handler(*args, **kwargs):
        return {"content": '<complete success="true">done</complete>', "usage": None}

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        await agent.ai_act("run")
    assert not list((tmp_path / "report").glob("*.json"))


def test_should_produce_valid_html_with_parseable_image_map_and_dump_json(
    tmp_path, monkeypatch
):
    from midscene.core.report import write_report_html

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    dump = {
        "sdkVersion": "0.2.0",
        "groupName": "g",
        "deviceType": "web",
        "executions": [
            {
                "name": "Tap - the button",
                "tasks": [
                    {
                        "type": "Action Space",
                        "subType": "Tap",
                        "status": "finished",
                        "param": {"locate": {"prompt": "the button"}},
                        "usage": {
                            "total_tokens": 5,
                            "prompt_tokens": 3,
                            "completion_tokens": 2,
                        },
                    }
                ],
            }
        ],
    }
    path = write_report_html(dump, "unit-report", run_dir=str(tmp_path))
    assert path and path.endswith(".html")
    content = open(path).read()
    assert "Tap - the button" in content
    assert '"groupName": "g"' in content or "groupName" in content
    assert "midscene_report_dump" in content


@pytest.mark.asyncio
async def test_ai_act_writes_html_report(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    agent = _agent()
    responses = ['<complete success="true">done</complete>']
    calls = {"n": 0}

    async def planning_handler(*args, **kwargs):
        calls["n"] += 1
        return {"content": responses[calls["n"] - 1], "usage": None}

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        await agent.ai_act("just finish")
    files = list((tmp_path / "report").glob("*.html"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "just finish" in content
