"""CLI tests for YAML target construction."""

import importlib

import pytest


@pytest.mark.asyncio
async def test_web_section_maps_to_playwright_options(monkeypatch):
    cli_main = importlib.import_module("midscene.cli.main")
    from midscene.web import PlaywrightWebPage

    captured = {}

    class FakePage:
        async def navigate_to(self, url):
            captured["url"] = url

        async def close(self):
            captured["closed"] = True

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return FakePage()

    monkeypatch.setattr(PlaywrightWebPage, "create", fake_create)

    page, options = await cli_main._create_agent_for_script(
        {
            "web": {
                "url": "https://example.com",
                "viewportWidth": 1440,
                "viewportHeight": 900,
                "userAgent": "midscene-test-agent",
                "chromeArgs": ["--disable-gpu", "-no-sandbox"],
            }
        },
        headed=False,
        device_id=None,
    )

    assert isinstance(page, FakePage)
    assert captured["headless"] is True
    assert captured["viewport_size"] == (1440, 900)
    assert captured["user_agent"] == "midscene-test-agent"
    assert captured["args"] == ["--disable-gpu", "-no-sandbox"]
    assert captured["url"] == "https://example.com"
    assert options.cache_id is None


@pytest.mark.parametrize(
    "status,failed_tasks,expected_exit",
    [
        ("done", [], 0),
        ("done", [{"name": "flaky", "error": "boom"}], 1),
        ("error", [{"name": "flaky", "error": "boom"}], 1),
    ],
)
def test_run_exit_code_reflects_failed_tasks(
    tmp_path, monkeypatch, status, failed_tasks, expected_exit
):
    import midscene.core.agent as agent_module
    import midscene.core.yaml_runner as yaml_module
    from typer.testing import CliRunner

    cli_main = importlib.import_module("midscene.cli.main")

    script_path = tmp_path / "flow.yaml"
    script_path.write_text(
        "tasks:\n  - name: flaky\n    continueOnError: true\n"
        "    flow:\n      - sleep: 1\n"
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

    monkeypatch.setattr(
        agent_module, "Agent", lambda *a, **k: FakeAgent()
    )
    monkeypatch.setattr(yaml_module, "ScriptPlayer", lambda *a, **k: FakePlayer())
    monkeypatch.setattr(cli_main, "_create_agent_for_script", fake_create)

    result = CliRunner().invoke(cli_main.app, ["run", str(script_path)])

    assert result.exit_code == expected_exit
    if failed_tasks:
        assert "boom" in result.output
