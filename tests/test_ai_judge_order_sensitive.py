"""Synced from upstream packages/core/tests/unit-test/ai-judge-order-sensitive.test.ts."""

import pytest


@pytest.mark.asyncio
async def test_judges_order_sensitivity_with_generated_messages(monkeypatch):
    from midscene.core.ai_model.workflows.insight import order_sensitive

    captured = {}

    async def fake_call(messages, runtime, options):
        captured["messages"] = messages
        return {"content": '{"isOrderSensitive": true}'}

    monkeypatch.setattr(order_sensitive, "call_generative_ai", fake_call)
    result = await order_sensitive.resolve_order_sensitive(
        {"target_description": "the second button", "model_runtime": object()}
    )

    assert result is True
    assert "the second button" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_falls_back_to_false_when_the_judge_cannot_run(monkeypatch):
    from midscene.core.ai_model.workflows.insight import order_sensitive

    async def fail_call(*args, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(order_sensitive, "call_generative_ai", fail_call)

    assert await order_sensitive.resolve_order_sensitive(None) is False
    assert (
        await order_sensitive.resolve_order_sensitive(
            {"target_description": "x", "model_runtime": object()}
        )
        is False
    )
