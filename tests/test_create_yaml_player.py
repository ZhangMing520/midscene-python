"""Port of upstream packages/cli/tests/unit-test/create-yaml-player.test.ts.

The Python port exposes the target construction as
``create_agent_for_script`` (the upstream ``createYamlPlayer`` setup callback).
The web-target case is ported; cases that assert the Node-only
``puppeteerAgentForTarget``/``ScriptPlayer`` call shapes have no Python
counterpart and are not included.
"""

from typing import get_type_hints

import pytest

from midscene.cli.create_yaml_player import ScriptAgent, create_agent_for_script
from midscene.core.agent.agent_options import AgentOptions


def test_script_agent_annotations_resolve_at_runtime():
    assert get_type_hints(ScriptAgent)["options"] is AgentOptions
    assert "return" in get_type_hints(create_agent_for_script)


@pytest.mark.asyncio
async def test_should_create_player_with_web_target(monkeypatch):
    from midscene.web_integration import PlaywrightWebPage

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

    page, options = await create_agent_for_script(
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
