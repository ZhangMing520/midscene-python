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
