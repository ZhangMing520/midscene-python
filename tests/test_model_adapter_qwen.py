"""Synced from upstream packages/core/tests/unit-test/model-adapter/qwen.test.ts."""


def test_keeps_qwen2_5_vl_high_resolution_image_request_flag_without_reasoning_params():
    from midscene.core.ai_model.models.registry import get_model_runtime

    runtime_qwen3 = get_model_runtime(
        {
            "modelName": "mock-model",
            "intent": "default",
            "slot": "default",
            "modelFamily": "qwen3-vl",
            "retryCount": 0,
            "retryInterval": 0,
            "responseFormat": "none",
        }
    )
    params = runtime_qwen3.adapter.build_chat_completion_params(
        {"temperature": 0.0}, {"reasoningEnabled": True}
    )
    assert params["enable_thinking"] is True

    runtime_qwen25 = get_model_runtime(
        {
            "modelName": "mock-model",
            "intent": "default",
            "slot": "default",
            "modelFamily": "qwen2.5-vl",
            "retryCount": 0,
            "retryInterval": 0,
            "responseFormat": "none",
        }
    )
    params25 = runtime_qwen25.adapter.build_chat_completion_params({}, {})
    assert params25["vl_high_resolution_images"] is True

    def test_qwen_single_item_array_unwrap_only_for_locate(self):
        from midscene.core.ai_model.models.registry import get_model_adapter
        from midscene.core.ai_model.shared.json import parse_model_response_json

        adapter = get_model_adapter("qwen3")
        raw = '[{"bbox_2d":[562,653,574,671],"label":"Approve checkbox"}]'
        parsed = adapter.json_parser(raw, "locate")
        assert parsed == {"bbox_2d": [562, 653, 574, 671], "label": "Approve checkbox"}

        parsed = adapter.json_parser(raw, "generic-object")
        assert isinstance(parsed, list)
        assert parse_model_response_json(raw) == [
            {"bbox_2d": [562, 653, 574, 671], "label": "Approve checkbox"}
        ]

        element = adapter.locate_protocol["element"]["parse_raw_response"](
            raw, adapter.locate_result_codec.prompt_spec
        )
        assert element["kind"] == "located"
        assert element["target"] == [562, 653, 574, 671]
