"""Synced from upstream packages/core/tests/unit-test/model-adapter.test.ts and
family adapter tests (stepfun/tencent-hy/qwen/kimi/deepseek/doubao/glm)."""


class TestModelAdapter:
    def test_deep_locate_support_flags(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        assert get_model_adapter("gpt-5").supports_action_deep_locate is True
        assert get_model_adapter("auto-glm").supports_action_deep_locate is False
        assert get_model_adapter("vlm-ui-tars").supports_action_deep_locate is False

    def test_kimi3_replays_raw_assistant_message(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        assert get_model_adapter("kimi3").replay_raw_assistant_message is True
        assert get_model_adapter("gpt-5").replay_raw_assistant_message is False

    def test_new_family_locate_formats(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        step = get_model_adapter("step").locate_result_codec.prompt_spec
        assert step["resultKey"] == "point_2d"
        assert step["resultKeyAliases"] == ["point"]

        tencent = get_model_adapter("tencent-hy").locate_result_codec.prompt_spec
        assert tencent["resultKey"] == "box_2d"
        assert tencent["resultValueSchema"] == "[number, number, number, number]"

        qwen4 = get_model_adapter("qwen4").locate_result_codec.prompt_spec
        assert qwen4["resultKey"] == "point"
        assert qwen4["resultKeyAliases"] == ["point_2d"]

    def test_reasoning_effort_only_when_enabled(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        for family in ("kimi3", "deepseek", "doubao-seed"):
            params = get_model_adapter(family).build_chat_completion_params(
                {}, {"reasoningEnabled": False, "reasoningEffort": "high"}
            )
            assert "reasoning_effort" not in params, family

        params = get_model_adapter("kimi3").build_chat_completion_params(
            {}, {"reasoningEnabled": True, "reasoningEffort": "high"}
        )
        assert params["reasoning_effort"] == "high"
        assert params["thinking"] == {"type": "enabled"}

        # "default" leaves native thinking untouched.
        params = get_model_adapter("glm-v").build_chat_completion_params(
            {}, {"reasoningEnabled": "default"}
        )
        assert "thinking" not in params

