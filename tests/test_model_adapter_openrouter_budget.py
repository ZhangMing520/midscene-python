"""Synced from upstream packages/core/tests/unit-test/model-adapter/
openrouter-budget.test.ts."""


class TestOpenRouterBudget:
    def test_openrouter_reasoning_shapes(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        params = get_model_adapter("qwen4").build_chat_completion_params(
            {}, {"reasoningEnabled": True, "reasoningBudget": 64}
        )
        assert params["enable_thinking"] is True
        assert params["thinking_budget"] == 64

        openrouter = {
            "baseURL": "https://openrouter.ai/api/v1",
            "reasoningEnabled": True,
            "reasoningEffort": "high",
            "reasoningBudget": 64,
        }
        params = get_model_adapter("qwen4").build_chat_completion_params(
            {}, openrouter
        )
        assert params["reasoning"] == {
            "enabled": True,
            "effort": "high",
            "max_tokens": 64,
        }
        assert "enable_thinking" not in params

        disabled = get_model_adapter("qwen4").build_chat_completion_params(
            {}, {"baseURL": "https://openrouter.ai/api/v1", "reasoningEnabled": False}
        )
        assert disabled["reasoning"] == {"enabled": False}

        step = get_model_adapter("step").build_chat_completion_params(
            {},
            {
                "baseURL": "https://openrouter.ai/api/v1",
                "reasoningEnabled": False,
            },
        )
        assert step["reasoning"] == {"effort": "low"}

        # The URL match is exact; a trailing slash is not OpenRouter.
        native = get_model_adapter("qwen4").build_chat_completion_params(
            {},
            {
                "baseURL": "https://openrouter.ai/api/v1/",
                "reasoningEnabled": True,
            },
        )
        assert "reasoning" not in native
        assert native["enable_thinking"] is True

