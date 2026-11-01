"""
Tests for the final P3 batch: WDA client (webdriver), recorder generation,
HTML report viewer, and the RDP device shell.
"""

import re
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest


# ---------------------------------------------------------------------------
# webdriver / WDA client
# ---------------------------------------------------------------------------


class FakeWDAHttp:
    """Records requests and returns canned parsed responses (make_request
    returns the parsed JSON body, so the stub does the same)."""

    def __init__(self, responses: Dict[str, Any]):
        self.responses = responses
        self.requests: List[tuple] = []

    async def __call__(self, method, url, json=None):
        self.requests.append((method, url, json))
        tail = url.split("://", 1)[-1].split("/", 1)[-1]
        # normalize /session/<id>/... to /session/... so patterns don't need ids
        key = f"{method} {tail}"
        normalized = re.sub(r"^(GET|POST|DELETE) session/[^/]+", r"\1 session", key)
        for pattern, payload in self.responses.items():
            if normalized.startswith(pattern) or key.startswith(pattern):
                return payload
        raise RuntimeError(f"WebDriver request failed (404) {method} {tail}: not found")


def path_placeholder(url):
    return url


class TestWdaClient:
    @pytest.mark.asyncio
    async def test_create_and_delete_session(self):
        from midscene.ios.wda import WebDriverClient

        http = FakeWDAHttp({
            "POST session": {"sessionId": "s1", "capabilities": {"platformName": "iOS"}},
            "DELETE session": {"value": None},
        })
        client = WebDriverClient(base_url="http://localhost:8100")
        client.make_request = http

        session = await client.create_session({"platformName": "iOS"})
        assert session["sessionId"] == "s1"
        assert client.session_id == "s1"
        assert client.owns_session is True

        await client.delete_session()
        assert client.session_id is None

    @pytest.mark.asyncio
    async def test_take_screenshot_and_window_size(self):
        from midscene.ios.wda import WebDriverClient

        http = FakeWDAHttp({
            "GET session/screenshot": {"value": "base64png"},
            "GET session/window/rect": {"value": {"width": 390, "height": 844}},
        })
        client = WebDriverClient(base_url="http://localhost:8100", session_id="ext-1")
        client.make_request = http
        # external session: owns_session False
        assert client.owns_session is False

        assert await client.take_screenshot() == "base64png"
        size = await client.get_window_size()
        assert size == (390, 844)

    @pytest.mark.asyncio
    async def test_window_size_falls_back_to_size_endpoint(self):
        from midscene.ios.wda import WebDriverClient

        http = FakeWDAHttp({
            "GET session/window/size": {"value": {"width": 100, "height": 200}},
        })
        client = WebDriverClient(base_url="http://x", session_id="s")

        async def fail_rect(method, path, body=None):
            if "rect" in path:
                raise RuntimeError("no rect endpoint")
            return await http(method, path, body)

        client.make_request = fail_rect
        assert await client.get_window_size() == (100, 200)

    @pytest.mark.asyncio
    async def test_device_info_from_status(self):
        from midscene.ios.wda import WebDriverClient

        http = FakeWDAHttp({
            "GET status": {"device": {"udid": "UDID-1", "name": "iPhone", "model": "15 Pro"}},
        })
        client = WebDriverClient(base_url="http://x")
        client.make_request = http
        info = await client.get_device_info()
        assert info["udid"] == "UDID-1"
        assert info["model"] == "15 Pro"

    def test_base_url_normalization(self):
        from midscene.ios.wda import normalize_webdriver_base_url

        assert normalize_webdriver_base_url("http://x:8100/") == "http://x:8100"
        assert normalize_webdriver_base_url("x:8100") == "http://x:8100"


# ---------------------------------------------------------------------------
# recorder generation
# ---------------------------------------------------------------------------


class TestRecorderGeneration:
    def _events(self) -> List[Dict[str, Any]]:
        return [
            {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
            {"type": "click", "description": "search box", "timestamp": 2},
            {"type": "input", "description": "search box", "value": "shoes", "timestamp": 3},
            {"type": "scroll", "timestamp": 4},
        ]

    def test_validate_rejects_empty(self):
        from midscene.core.recorder_generation import validate_events

        with pytest.raises(ValueError):
            validate_events([])
        with pytest.raises(ValueError):
            validate_events([{"timestamp": 1}])

    def test_event_counts(self):
        from midscene.core.recorder_generation import create_event_counts

        counts = create_event_counts(self._events())
        assert counts["navigation"] == 1
        assert counts["click"] == 1
        assert counts["input"] == 1
        assert counts["scroll"] == 1
        assert counts["total"] == 4

    def test_semantic_ready_preferred(self):
        from midscene.core.recorder_generation import process_events_for_llm

        events = [{
            "type": "click",
            "description": "raw desc",
            "semantic": {
                "source": "aiDescribe",
                "status": "ready",
                "elementDescription": "the blue cart button",
                "replayInstruction": "click the cart",
            },
        }]
        processed = process_events_for_llm(events)
        assert processed[0]["description"] == "the blue cart button"
        assert processed[0]["value"] == "click the cart"

    def test_default_web_target_from_navigation(self):
        from midscene.core.recorder_generation import create_default_web_target

        target = create_default_web_target(self._events(), {})
        assert target["platformId"] == "web"
        assert target["values"]["url"] == "https://shop.example"

    def test_normalize_strips_fences(self):
        from midscene.core.recorder_generation import normalize_generated_yaml

        assert normalize_generated_yaml("```yaml\n- type: Tap\n```") == "- type: Tap\n"
        assert normalize_generated_yaml("- type: Tap") == "- type: Tap\n"

    @pytest.mark.asyncio
    async def test_generate_yaml_test(self):
        from midscene.core.recorder_generation import generate_yaml_test

        captured: Dict[str, Any] = {}

        async def fake_call(prompt, runtime):
            captured["prompt"] = prompt
            return {"content": "```yaml\nweb:\n  url: https://shop.example\ntasks: []\n```"}

        runtime = Mock()
        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            yaml_out = await generate_yaml_test(self._events(), {}, runtime)

        assert yaml_out.startswith("web:\n")
        system_prompt = captured["prompt"][0]["content"]
        assert "aiTap" in system_prompt
        user_prompt = captured["prompt"][1]["content"]
        assert "https://shop.example" in user_prompt
        assert "Return ONLY the raw YAML content" in user_prompt

    @pytest.mark.asyncio
    async def test_generate_wraps_errors(self):
        from midscene.core.recorder_generation import generate_yaml_test

        async def fake_call(prompt, runtime):
            raise RuntimeError("model down")

        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            with pytest.raises(RuntimeError) as exc:
                await generate_yaml_test(self._events(), {}, Mock())
        assert "Failed to generate recorder YAML test" in str(exc.value)


# ---------------------------------------------------------------------------
# HTML report viewer
# ---------------------------------------------------------------------------


class TestReportViewer:
    def test_writes_viewable_html(self, tmp_path, monkeypatch):
        from midscene.core.report_viewer import write_report_html

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
                            "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
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
    async def test_ai_act_writes_html_report(self, mock_interface, tmp_path, monkeypatch):
        from tests.test_core import patch_model_call

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = _simple_agent()
        responses = ['<complete success="true">done</complete>']
        calls = {"n": 0}

        async def planning_handler(*args, **kwargs):
            calls["n"] += 1
            return {"content": responses[calls["n"] - 1], "usage": None}

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ):
            await agent.ai_act("just finish")
        files = list((tmp_path / "report").glob("*.html"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "just finish" in content


@pytest.fixture
def mock_interface():
    from tests.test_core import MockInterface

    return MockInterface()


def _simple_agent():
    from midscene.core.agent import Agent
    from midscene.core.types import AgentOptions
    from tests.test_core import MockInterface

    return Agent(
        MockInterface(),
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "m",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            }
        ),
    )


# ---------------------------------------------------------------------------
# RDP device
# ---------------------------------------------------------------------------


class FakeRDPBackend:
    def __init__(self):
        self.calls: List[tuple] = []

    async def connect(self, config):
        self.calls.append(("connect", config))
        return {"sessionId": "rdp-1", "size": {"width": 1280, "height": 720}, "server": config["host"]}

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def screenshot_base64(self):
        self.calls.append(("screenshot",))
        return "base64png"

    async def size(self):
        self.calls.append(("size",))
        return {"width": 1280, "height": 720}

    async def mouse_move(self, x, y):
        self.calls.append(("mouse_move", x, y))

    async def mouse_button(self, button, action):
        self.calls.append(("mouse_button", button, action))

    async def wheel(self, direction, amount, x=None, y=None):
        self.calls.append(("wheel", direction, amount))

    async def key_press(self, key_name):
        self.calls.append(("key_press", key_name))

    async def type_text(self, text):
        self.calls.append(("type_text", text))


class TestRDPDevice:
    @pytest.mark.asyncio
    async def test_connect_and_context(self):
        from midscene.desktop.rdp import RDPDevice

        backend = FakeRDPBackend()
        device = RDPDevice({"host": "win-box"}, backend=backend)
        assert device.interface_type.value == "computer"
        await device.connect()
        context = await device.get_context()
        assert context.size.width == 1280
        assert any(c[0] == "screenshot" for c in backend.calls)

    @pytest.mark.asyncio
    async def test_input_primitives_delegate(self):
        from midscene.desktop.rdp import RDPDevice

        backend = FakeRDPBackend()
        device = RDPDevice({"host": "win-box"}, backend=backend)
        await device.tap(10, 20)
        await device.right_click(10, 20)
        await device.double_click(10, 20)
        await device.input_text("hello")
        await device.keyboard_press("Enter")
        await device.scroll("down", 300)
        assert ("mouse_move", 10, 20) in backend.calls
        assert ("mouse_button", "right", "click") in backend.calls
        assert ("mouse_button", "left", "doubleClick") in backend.calls
        assert ("type_text", "hello") in backend.calls
        assert ("key_press", "Enter") in backend.calls
        assert ("wheel", "down", 300) in backend.calls

    @pytest.mark.asyncio
    async def test_default_backend_raises_not_implemented(self):
        """Faithful upstream state: the transport is unimplemented until a
        custom backend is injected."""
        from midscene.desktop.rdp import RDPDevice

        device = RDPDevice({"host": "win-box"})
        with pytest.raises(RuntimeError) as exc:
            await device.connect()
        assert "not implemented yet" in str(exc.value)

    def test_helper_binary_missing_reports_platform(self):
        from midscene.desktop.rdp import get_rdp_helper_binary_path

        with pytest.raises(RuntimeError) as exc:
            get_rdp_helper_binary_path(package_root="/nonexistent")
        assert "rdp-helper" in str(exc.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestRecorderMarkdownGeneration:
    def _events(self):
        return [
            {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
            {"type": "click", "description": "search box", "timestamp": 2},
            {"type": "input", "description": "search box", "value": "shoes", "timestamp": 3},
        ]

    def test_normalize_markdown_strips_fences(self):
        from midscene.core.recorder_generation import normalize_generated_markdown

        assert normalize_generated_markdown("```md\n# Title\n```") == "# Title\n"
        assert normalize_generated_markdown("# Plain") == "# Plain\n"

    def test_payload_budget_limits_assets(self):
        from midscene.core.recorder_generation import (
            limit_screenshot_assets_for_markdown_replay,
        )

        big = {"dataUrl": "x" * 700_000, "eventIndex": 0, "eventHashId": "a"}
        small = {"dataUrl": "y" * 100, "eventIndex": 1, "eventHashId": "b"}
        kept = limit_screenshot_assets_for_markdown_replay([big, small])
        # the oversized asset is dropped, the small one kept
        assert kept == [small]

    def test_prompt_structure_and_screenshot_refs(self):
        from midscene.core.recorder_generation import (
            create_recorder_markdown_replay_prompt,
            prepare_event_summary,
        )

        events = self._events()
        target = {"platformId": "web", "label": "Web", "values": {"url": "https://shop.example"}}
        summary = prepare_event_summary(events, {})
        assets = [
            {"eventIndex": 1, "eventHashId": summary["events"][1]["hashId"],
             "eventType": "click", "dataUrl": "data:image/jpeg;base64,AAA",
             "relativePath": "shot-1.jpeg"}
        ]
        input_payload = {"testName": "checkout", "target": target, "events": events}
        prompt = create_recorder_markdown_replay_prompt(input_payload, summary, assets)

        # system role
        assert prompt[0]["role"] == "system"
        assert "agent.aiAct" in prompt[0]["content"]

        # user content carries the prompt text and one screenshot pair
        user_content = prompt[1]["content"]
        text_part = user_content[0]["text"]
        assert "screenshot-1" in text_part
        assert "Required structure:" in text_part
        assert "# checkout" in text_part
        assert "Never write Markdown image syntax" in text_part
        # image follows its label
        assert user_content[1]["text"].startswith("screenshot-1 for event #2")
        assert user_content[2]["type"] == "image"

    @pytest.mark.asyncio
    async def test_generate_markdown_replay(self):
        from midscene.core.recorder_generation import generate_markdown_replay

        captured: Dict[str, Any] = {}

        async def fake_call(prompt, runtime):
            captured["prompt"] = prompt
            return {"content": "```md\n# checkout\n## Steps\n1. tap search\n```"}

        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            result = await generate_markdown_replay(self._events(), {}, Mock())

        assert result.startswith("# checkout\n")
        system_prompt = captured["prompt"][0]["content"]
        assert "must not contain image references" in system_prompt

    @pytest.mark.asyncio
    async def test_generate_markdown_wraps_errors(self):
        from midscene.core.recorder_generation import generate_markdown_replay

        async def fake_call(prompt, runtime):
            raise RuntimeError("down")

        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            with pytest.raises(RuntimeError) as exc:
                await generate_markdown_replay(self._events(), {}, Mock())
        assert "Failed to generate recorder Markdown replay" in str(exc.value)


class TestRecorderPlaywrightGeneration:
    @pytest.mark.asyncio
    async def test_generate_playwright_test(self):
        from midscene.core.recorder_generation import generate_playwright_test

        captured: Dict[str, Any] = {}

        async def fake_call(prompt, runtime):
            captured["prompt"] = prompt
            return {"content": "```typescript\nimport { test } from '@playwright/test';\n```"}

        events = [
            {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
            {"type": "click", "description": "buy", "timestamp": 2},
        ]
        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            result = await generate_playwright_test(events, {"testName": "buy-flow"}, Mock())

        assert result.startswith("import { test }")
        user_prompt = captured["prompt"][1]["content"]
        assert "@midscene/web/playwright" in user_prompt
        assert "https://shop.example" in user_prompt
        assert "Return ONLY the raw Playwright test code" in user_prompt

    @pytest.mark.asyncio
    async def test_playwright_summary_options(self):
        from midscene.core.recorder_generation import generate_playwright_test

        captured: Dict[str, Any] = {}

        async def fake_call(prompt, runtime):
            captured["prompt"] = prompt
            return {"content": "// test"}

        events = [{"type": "click", "timestamp": 1}]
        with patch(
            "midscene.core.recorder_generation.call_ai_with_string_response",
            new=fake_call,
        ):
            await generate_playwright_test(
                events,
                {"viewportSize": {"width": 800, "height": 600}, "waitForNetworkIdleTimeout": 3000},
                Mock(),
            )
        summary_text = captured["prompt"][1]["content"]
        assert '"viewportSize"' in summary_text
        assert "800" in summary_text
        assert "3000" in summary_text
