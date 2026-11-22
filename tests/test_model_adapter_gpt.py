"""Synced from upstream packages/core/tests/unit-test/model-adapter/gpt.test.ts."""


class TestGptAdapter:
    def test_gpt5_responses_json_mode_only_when_expected(self):
        from midscene.core.ai_model.models.registry import get_model_adapter

        adapter = get_model_adapter("gpt-5")
        params = adapter.build_responses_params(
            {}, {"responseFormat": "json_object"}, True
        )
        assert params["text"] == {"format": {"type": "json_object"}}

        params = adapter.build_responses_params(
            {}, {"responseFormat": "json_object"}, False
        )
        assert "text" not in params

    def test_unset_temperature_removed_from_request(self):
        from midscene.core.ai_model.service_caller.openai import chat_completion, responses
        from midscene.core.ai_model.models.registry import get_model_runtime

        runtime = get_model_runtime(
            {
                "modelName": "mock-model",
                "modelFamily": "gpt-5",
                "temperature": "unset",
                "retryCount": 0,
            }
        )
        chat = chat_completion.prepare_chat_completion(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert "temperature" not in chat["request_body"]

        responses = responses.prepare_responses(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert "temperature" not in responses["request_body"]

