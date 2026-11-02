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


@pytest.mark.asyncio
async def test_computer_section_builds_desktop_agent():
    cli_main = importlib.import_module("midscene.cli.main")
    from midscene.desktop import DesktopAgent

    agent = await cli_main._create_agent_for_script(
        {"computer": {"agent": {"groupName": "desktop run"}}},
        headed=False,
        device_id=None,
    )
    assert isinstance(agent, DesktopAgent)
    assert agent.interface_type.value == "computer"


@pytest.mark.asyncio
async def test_computer_section_refuses_display_id():
    """The pyautogui backend grabs the primary display only, so a declared
    displayId must fail loudly instead of being ignored."""
    cli_main = importlib.import_module("midscene.cli.main")

    with pytest.raises(NotImplementedError):
        await cli_main._create_agent_for_script(
            {"computer": {"displayId": "1"}}, headed=False, device_id=None
        )


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


def test_cli_target_overrides_parse_dotted_flags():
    cli_main = importlib.import_module("midscene.cli.main")

    overrides = cli_main._parse_cli_target_overrides(
        [
            "--web.viewport-width",
            "1440",
            "--web.accept-insecure-certs",
            "true",
            "--android.device-id",
            "emulator-5554",
            "--unknown.flag",
            "x",
        ]
    )
    assert overrides == {
        "web": {"viewportWidth": 1440, "acceptInsecureCerts": True},
        "android": {"deviceId": "emulator-5554"},
    }

    script = {"web": {"url": "https://example.com", "viewportWidth": 800}}
    merged = cli_main._merge_cli_target_overrides(script, overrides)
    # The script's own keys win over CLI defaults (batch merge order).
    assert merged["web"]["viewportWidth"] == 800
    assert merged["web"]["acceptInsecureCerts"] is True
    assert merged["android"]["deviceId"] == "emulator-5554"


def test_dotenv_loader_respects_override(tmp_path, monkeypatch):
    cli_main = importlib.import_module("midscene.cli.main")
    env_file = tmp_path / ".env"
    env_file.write_text("MIDSCENE_TEST_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MIDSCENE_TEST_KEY", "from-env")

    cli_main._load_dotenv(override=False)
    assert __import__("os").environ["MIDSCENE_TEST_KEY"] == "from-env"
    cli_main._load_dotenv(override=True)
    assert __import__("os").environ["MIDSCENE_TEST_KEY"] == "from-file"


def test_report_tool_split_markdown_and_merge(tmp_path):
    from typer.testing import CliRunner
    from midscene.core.report_viewer import (
        merge_report_files,
        report_file_to_markdown,
        split_report_file,
        write_report_html,
    )

    cli_main = importlib.import_module("midscene.cli.main")
    dump = {
        "sdkVersion": "0.2.0",
        "groupName": "Report tool",
        "groupDescription": "demo",
        "modelBriefs": [],
        "deviceType": "web",
        "executions": [
            {
                "id": "a1",
                "name": "first",
                "tasks": [
                    {
                        "type": "Planning",
                        "status": "finished",
                        "param": {"userInstruction": "hello"},
                        "output": "done",
                    }
                ],
            },
            {
                "id": "a2",
                "name": "second",
                "tasks": [
                    {
                        "type": "Screenshot",
                        "status": "finished",
                        "output": [{"base64": "aGVsbG8="}],
                    }
                ],
            },
        ],
    }
    # Render twice so merge can exercise dedupe-by-id (keep latest).
    html_path = write_report_html(dump, "report-tool-fixture", str(tmp_path))
    assert html_path

    split_dir = tmp_path / "split"
    split = split_report_file(html_path, str(split_dir))
    assert len(split["executionJsonFiles"]) == 2
    assert (split_dir / "1.execution.json").exists()

    markdown_dir = tmp_path / "md"
    markdown = report_file_to_markdown(html_path, str(markdown_dir))
    assert (markdown_dir / "report.md").exists()
    assert markdown["markdownFiles"]
    assert "## 1. first" in (markdown_dir / "report.md").read_text(encoding="utf-8")

    merged_dir = tmp_path / "merged"
    merged = merge_report_files(
        [html_path, html_path], str(merged_dir), "merged", overwrite=True
    )
    assert (merged_dir / "merged.html").exists()
    assert merged["mergedReportPath"].endswith("merged.html")

    result = CliRunner().invoke(
        cli_main.app,
        [
            "report-tool",
            "--action",
            "split",
            "--htmlPath",
            html_path,
            "--outputDir",
            str(tmp_path / "cli-split"),
        ],
    )
    assert result.exit_code == 0
    assert "Report split completed" in result.output
