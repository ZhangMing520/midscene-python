"""Synced from upstream packages/core/tests/unit-test/service-caller-temperature.test.ts."""



class TestServiceCallerTemperature:
    def test_semantic_retry_temperature(self):
        from midscene.core.ai_model.models.registry import get_model_runtime
        from midscene.core.ai_model.service_caller.openai.chat_completion import prepare_chat_completion

        runtime = get_model_runtime(
            {
                "modelName": "mock-model",
                "responseFormat": "none",
            }
        )
        first = prepare_chat_completion(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert first["request_body"]["temperature"] == 0.0

        retry = prepare_chat_completion(
            [{"role": "user", "content": "hi"}],
            runtime,
            {"semanticRetryAttempt": 1},
        )
        assert retry["request_body"]["temperature"] == 0.2

