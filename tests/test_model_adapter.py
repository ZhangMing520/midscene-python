"""Synced from upstream packages/core/tests/unit-test/model-adapter.test.ts and
family adapter tests (stepfun/tencent-hy/qwen/kimi/deepseek/doubao/glm)."""


class TestModelAdapter:
    def test_planning_adapter_annotations_resolve_at_runtime(self):
        from typing import get_type_hints

        from midscene.core.ai_model.model_adapter.planning import PlanningAdapter
        from midscene.core.ai_model.workflows.planning.types import PlanFn

        assert get_type_hints(PlanningAdapter)["plan_fn"] == PlanFn | None

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


class TestAdapterDefinitions:
    def test_registry_map_matches_upstream_families(self):
        from midscene.core.ai_model.models.registry import MODEL_ADAPTER_CONFIGS

        assert sorted(MODEL_ADAPTER_CONFIGS) == [
            "ant-ling",
            "auto-glm",
            "auto-glm-multilingual",
            "deepseek",
            "doubao-seed",
            "doubao-vision",
            "gemini",
            "glm-v",
            "gpt-5",
            "gpt-6",
            "jev",
            "kimi",
            "kimi3",
            "qwen2.5-vl",
            "qwen3",
            "qwen3-vl",
            "qwen3.5",
            "qwen3.6",
            "qwen4",
            "step",
            "tencent-hy",
            "vlm-ui-tars",
            "vlm-ui-tars-doubao",
            "vlm-ui-tars-doubao-1.5",
            "xiaomi-mimo",
        ]

    def test_deepseek_definition_config(self):
        from midscene.core.ai_model.models.deepseek.adapter import (
            deep_seek_adapters,
        )
        from midscene.core.ai_model.models.deepseek.locate_protocol import (
            deep_seek_element_locate_protocol,
            deep_seek_search_area_protocol,
        )

        definition = deep_seek_adapters["deepseek"]
        assert definition["chat_completion"]["use_reasoning_as_content_fallback"]
        assert not definition["chat_completion"]["replay_raw_assistant_message"]
        assert (
            definition["locate"]["element"]["protocol"]
            is deep_seek_element_locate_protocol
        )
        assert (
            definition["locate"]["search_area"]["protocol"]
            is deep_seek_search_area_protocol
        )

    def test_default_openai_compatible_definition(self):
        from midscene.core.ai_model.models.default import (
            default_open_ai_compatible_adapter_config,
        )

        assert default_open_ai_compatible_adapter_config == {
            "chat_completion": {"use_reasoning_as_content_fallback": True}
        }

    def test_resolved_model_adapter_from_config(self):
        from midscene.core.ai_model.model_adapter.resolve import (
            ResolvedModelAdapter,
        )

        adapter = ResolvedModelAdapter.from_config(
            {
                "model_type": "system-one",
                "allowed_task_types": ["locate"],
                "supported_protocols": [],
                "image_preprocess": {"padBlockSize": 28},
                "planning": {"kind": "custom"},
                "locate": {"kind": "custom"},
            }
        )
        assert adapter.model_type == "system-one"
        assert adapter.allowed_task_types == ["locate"]
        assert adapter.supported_protocols == []
        assert adapter.image_preprocess == {"padBlockSize": 28}
        assert adapter.planning == {"kind": "custom"}
        assert adapter.locate == {"kind": "custom"}
        assert adapter.chat_completion["use_reasoning_as_content_fallback"] is False

    def test_resolved_model_adapter_is_a_class(self):
        from midscene.core.ai_model.model_adapter.resolve import (
            ResolvedModelAdapter,
        )

        assert isinstance(ResolvedModelAdapter(), ResolvedModelAdapter)

    def test_resolve_responses_replays_raw_assistant_output(self):
        from midscene.core.ai_model.model_adapter.responses import (
            resolve_responses,
        )

        adapter = resolve_responses(None)
        assert set(adapter) == {
            "replay_raw_assistant_output",
            "build_responses_params",
        }
        assert adapter["replay_raw_assistant_output"] is False
        adapter = resolve_responses({"replay_raw_assistant_output": True})
        assert adapter["replay_raw_assistant_output"] is True
        assert adapter["build_responses_params"]({}) == {"config": {"temperature": 0}}

    def test_build_open_router_reasoning_params(self):
        from midscene.core.ai_model.model_adapter.openrouter_reasoning import (
            build_open_router_reasoning_params,
        )

        assert build_open_router_reasoning_params({}) == {
            "reasoning": {"enabled": False}
        }
        assert (
            build_open_router_reasoning_params(
                {"reasoningEnabled": "default", "reasoningEffort": "high"}
            )
            == {}
        )
        assert build_open_router_reasoning_params(
            {
                "reasoningEnabled": True,
                "reasoningEffort": "high",
                "reasoningBudget": 4096,
            }
        ) == {"reasoning": {"enabled": True, "effort": "high", "max_tokens": 4096}}
        assert build_open_router_reasoning_params(
            {"reasoningEnabled": False},
            {
                "type": "effort",
                "defaultEnabledEffort": "medium",
                "disabledEffort": "low",
            },
        ) == {"reasoning": {"effort": "low"}}

    def test_temperature_with_semantic_retry(self):
        from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
            get_temperature_with_semantic_retry,
        )

        assert get_temperature_with_semantic_retry(0) == 0
        assert get_temperature_with_semantic_retry(0, 1, 0) == 0
        assert get_temperature_with_semantic_retry(0, None, 1) == 0.2
        assert get_temperature_with_semantic_retry(0, 0, 1) == 0
        assert get_temperature_with_semantic_retry(0.5, None, 1) == 0.5
        assert get_temperature_with_semantic_retry(None, None, 1) is None
