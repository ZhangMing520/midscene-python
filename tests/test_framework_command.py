"""Port of upstream packages/cli/tests/unit-test/framework/command.test.ts.

Only the exit-code contract is ported: a completed run exits 0, while an
``error`` player or a ``partialFailed`` run (``continueOnError`` produced
failed tasks) exits non-zero. The Python CLI wires this in
``midscene/cli/index.py::run``.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "status,failed_tasks,expected_exit",
    [
        ("done", [], 0),
        ("done", [{"name": "flaky", "error": "boom"}], 1),
        ("error", [{"name": "flaky", "error": "boom"}], 1),
    ],
)
def test_continues_after_partial_failed_files_but_exits_non_zero_from_summary(
    tmp_path, monkeypatch, status, failed_tasks, expected_exit
):
    from typer.testing import CliRunner

    import midscene.core.agent.agent as agent_module
    import midscene.core.yaml as yaml_module

    cli_main = importlib.import_module("midscene.cli.index")

    script_path = tmp_path / "flow.yaml"
    script_path.write_text(
        "tasks:\n  - name: flaky\n    continueOnError: true\n"
        "    flow:\n      - sleep: 1\n",
        encoding="utf-8",
    )

    class FakePlayer:
        def __init__(self):
            self.status = status
            self.failed_tasks = failed_tasks
            self.output_path = None

        async def run(self):
            return None

    class FakePage:
        async def close(self):
            return None

    class FakeAgent:
        async def destroy(self):
            return None

    async def fake_create(script, headed, device_id):
        return FakePage(), object()

    monkeypatch.setattr(agent_module, "Agent", lambda *a, **k: FakeAgent())
    monkeypatch.setattr(yaml_module, "ScriptPlayer", lambda *a, **k: FakePlayer())
    monkeypatch.setattr(cli_main, "_create_agent_for_script", fake_create)

    result = CliRunner().invoke(cli_main.app, ["run", str(script_path)])

    assert result.exit_code == expected_exit
    if failed_tasks:
        assert "boom" in result.output
