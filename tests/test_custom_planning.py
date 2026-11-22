"""Synced from upstream packages/core/tests/unit-test/custom-planning.test.ts."""

from types import SimpleNamespace

import pytest

from midscene.core.ai_model.workflows.planning import custom_planning
from midscene.core.ai_model.workflows.planning.conversation_history import (
    ConversationHistory,
)


def _config() -> dict:
    return {
        "messages": {
            "build_system_prompt": lambda: "system prompt",
            "system_prompt_placement": "system-message",
            "history_image_limit": 1,
        },
        "parse_response": lambda content, context, runtime: [],
        "transform_actions": lambda parsed, context, action_space, runtime: [],
        "coordinates": {},
        "should_continue_planning": lambda parsed, actions: False,
        "build_response_log": lambda parsed, content: None,
    }


@pytest.mark.asyncio
async def test_consumes_pending_feedback_in_the_latest_screenshot_message(monkeypatch):
    conversation_history = ConversationHistory()
    conversation_history.pending_feedback_message = (
        "Current time: 2026-06-16 19:35:17 (YYYY-MM-DD HH:mm:ss)"
    )
    captured = {}

    async def fake_call(messages, model_runtime, options):
        captured["messages"] = messages
        return {"content": "[]", "usage": None}

    monkeypatch.setattr(
        custom_planning, "call_ai_with_string_response", fake_call
    )

    context = SimpleNamespace(
        screenshot_base64="data:image/png;base64,SCREENSHOT==",
        size=SimpleNamespace(width=1000, height=800),
    )
    model_runtime = SimpleNamespace(
        adapter=SimpleNamespace(image_pad_block_size=None)
    )

    await custom_planning.run_custom_planning(
        "click save",
        context,
        model_runtime,
        [],
        conversation_history,
        _config(),
        include_locate_in_planning=True,
    )

    messages = captured["messages"]
    assert conversation_history.pending_feedback_message == ""
    assert messages[-2]["type"] == "input-message"
    assert messages[-2]["message"]["role"] == "user"
    feedback_text = messages[-2]["message"]["content"][0]["text"]
    assert feedback_text.startswith(
        "Current time: 2026-06-16 19:35:17 (YYYY-MM-DD HH:mm:ss)"
    )
    assert "The previous action has been executed" in feedback_text
    assert messages[-1]["type"] == "input-message"
    assert messages[-1]["message"]["role"] == "user"
    assert messages[-1]["message"]["content"][0] == {
        "type": "image",
        "url": "data:image/png;base64,SCREENSHOT==",
    }
