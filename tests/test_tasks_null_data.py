"""Synced from upstream packages/core/tests/unit-test/tasks-null-data.test.ts."""

import json
from typing import Any, List

import pytest

from tests.core_helpers import MockInterface, patch_model_call


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


class TestTypedQueryParity:
    @pytest.mark.asyncio
    async def test_boolean_query_uses_type_key(self):
        calls: List[Any] = []

        async def handler(*args, **kwargs):
            calls.append(args[0])
            return {
                "content": '<data-json>{"Boolean": true}</data-json>',
                "usage": None,
            }

        agent = _make_agent(MockInterface())
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight.extraction", handler
        ):
            assert await agent.ai_boolean("is loaded") is True

        assert "Boolean, based on the current screenshot" in json.dumps(
            calls[0], ensure_ascii=False
        )

    @pytest.mark.asyncio
    async def test_wait_for_uses_statement_key(self):
        calls: List[Any] = []

        async def handler(*args, **kwargs):
            calls.append(args[0])
            return {
                "content": '<data-json>{"StatementIsTruthy": true}</data-json>',
                "usage": None,
            }

        agent = _make_agent(MockInterface())
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight.extraction", handler
        ):
            await agent.ai_wait_for("loaded", {"timeoutMs": 100, "checkIntervalMs": 10})

        assert "the user wants to do some 'wait for' operation" in json.dumps(
            calls[0], ensure_ascii=False
        )

    @pytest.mark.asyncio
    async def test_ai_query_returns_json_array(self):
        async def handler(*args, **kwargs):
            return {
                "content": (
                    "<observation>Two rows</observation>"
                    '<data-json>[{"name": "a"}, {"name": "b"}]</data-json>'
                ),
                "usage": None,
            }

        agent = _make_agent(MockInterface())
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight.extraction", handler
        ):
            result = await agent.ai_query("list every row")

        assert result == [{"name": "a"}, {"name": "b"}]

