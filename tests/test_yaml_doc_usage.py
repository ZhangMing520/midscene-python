"""Synced from upstream packages/core/tests/unit-test/yaml-doc-usage.test.ts."""

import json

import pytest

from tests.core_helpers import MockInterface


class TestYamlEnvironment:
    def test_env_interpolation_inside_tasks(self, monkeypatch):
        from midscene.core.yaml import parse_yaml_script

        monkeypatch.setenv("TASK_NAME", "hello")
        script = parse_yaml_script(
            "tasks:\n  - name: ${TASK_NAME}\n    flow:\n      - sleep: 10\n"
        )
        assert script["tasks"][0]["name"] == "hello"

    def test_env_interpolation_keeps_unresolved_refs_in_tasks(self, monkeypatch):
        from midscene.core.yaml import parse_yaml_script

        monkeypatch.delenv("NOT_DEFINED_VAR", raising=False)
        script = parse_yaml_script(
            "tasks:\n  - name: ${NOT_DEFINED_VAR}\n    flow:\n      - sleep: 10\n"
        )
        assert script["tasks"][0]["name"] == "${NOT_DEFINED_VAR}"

    def test_env_interpolation_missing_outside_tasks_raises(self, monkeypatch):
        from midscene.core.yaml import parse_yaml_script

        monkeypatch.delenv("NOT_DEFINED_VAR", raising=False)
        with pytest.raises(ValueError, match="NOT_DEFINED_VAR"):
            parse_yaml_script("web:\n  url: ${NOT_DEFINED_VAR}\ntasks: []\n")


def _make_agent(interface):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    return Agent(
        interface,
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "mock-model",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            }
        ),
    )


class TestYamlExtras:
    @pytest.mark.asyncio
    async def test_javascript_and_json_output(self, tmp_path):
        from midscene.core.yaml import ScriptPlayer, parse_yaml_script

        output = tmp_path / "result.json"
        script = parse_yaml_script(
            "config:\n"
            f"  output: {output}\n"
            "tasks:\n"
            "  - name: t\n"
            "    flow:\n"
            "      - javascript:\n"
            "          script: document.title\n"
            "        name: title\n"
        )

        interface = MockInterface()

        async def evaluate_script(script_text):
            return "示例标题"

        interface.evaluate_script = evaluate_script

        player = ScriptPlayer(script, _make_agent(interface))
        await player.run()

        assert player.status == "done"
        assert json.loads(output.read_text(encoding="utf-8")) == {"title": "示例标题"}
