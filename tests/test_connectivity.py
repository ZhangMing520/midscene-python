"""Synced from upstream packages/core/tests/unit-test/connectivity.test.ts."""

from unittest.mock import AsyncMock, patch

import pytest


class TestConnectivity:
    @pytest.mark.asyncio
    async def test_text_check_passes_on_token(self):
        from midscene.core.ai_model.connectivity.run_connectivity_test import _run_check, _text_check

        async def fake_call(messages, runtime, options=None):
            return {"content": "CONNECTIVITY_OK", "usage": None}

        with patch(
            "midscene.core.ai_model.connectivity.run_connectivity_test.call_generative_ai",
            new=fake_call,
        ):
            result = await _run_check(
                "text", "planning", {"modelName": "m"}, _text_check
            )
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_text_check_fails_on_wrong_token(self):
        from midscene.core.ai_model.connectivity.run_connectivity_test import _run_check, _text_check

        async def fake_call(messages, runtime, options=None):
            return {"content": "HELLO", "usage": None}

        with patch(
            "midscene.core.ai_model.connectivity.run_connectivity_test.call_generative_ai",
            new=fake_call,
        ):
            result = await _run_check(
                "text", "planning", {"modelName": "m"}, _text_check
            )
        assert result["passed"] is False
        assert "Unexpected response" in result["message"]

    @pytest.mark.asyncio
    async def test_full_test_aggregates(self):
        from midscene.core.ai_model.connectivity import run_connectivity_test

        async def fake_call(messages, runtime, options=None):
            return {"content": "CONNECTIVITY_OK", "usage": None}

        config = {
            "defaultModelConfig": {"modelName": "m"},
            "planningModelConfig": {"modelName": "m"},
            "insightModelConfig": {"modelName": "m"},
        }
        with patch(
            "midscene.core.ai_model.connectivity.run_connectivity_test.call_generative_ai",
            new=fake_call,
        ), patch(
            "midscene.core.ai_model.connectivity.run_connectivity_test._vision_check",
            new=AsyncMock(return_value={"passed": True, "content": ""}),
        ), patch(
            "midscene.core.ai_model.connectivity.run_connectivity_test._ai_locate_check",
            new=AsyncMock(return_value={"passed": True, "content": ""}),
        ):
            result = await run_connectivity_test(config)
        assert result["passed"] is True
        assert len(result["checks"]) == 4
