"""Synced from upstream packages/core/tests/unit-test/model-adapter/chat-completion.test.ts."""

import pytest

from midscene.core.ai_model.models.registry import ModelRuntime, get_model_adapter
from midscene.core.ai_model.service_caller.openai.chat_completion.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.utils import extract_content_and_reasoning

DEFAULT_REASONING_KEYS = ["reasoning_content"]


def _extract(message, reasoning_keys=None):
    return extract_content_and_reasoning(
        message, reasoning_keys or DEFAULT_REASONING_KEYS
    )


def test_returns_empty_strings_for_undefined_input():
    """returns empty strings for undefined input"""
    assert _extract(None) == {"content": "", "reasoning_content": ""}


def test_extracts_string_content_and_reasoning_content():
    """extracts string content and reasoning_content"""
    assert _extract(
        {
            "content": "visible response",
            "reasoning_content": "reasoning response",
        }
    ) == {"content": "visible response", "reasoning_content": "reasoning response"}


def test_does_not_extract_reasoning_by_default_when_reasoning_content_is_absent():
    """does not extract reasoning by default when reasoning_content is absent"""
    assert _extract(
        {"content": "visible response", "reasoning": "vllm reasoning response"}
    ) == {"content": "visible response", "reasoning_content": ""}


def test_returns_empty_content_for_null_content():
    """returns empty content for null content"""
    assert _extract(
        {
            "role": "assistant",
            "content": None,
            "refusal": None,
            "reasoning_content": "top-level reasoning. ",
        }
    ) == {"content": "", "reasoning_content": "top-level reasoning. "}


def test_uses_configured_reasoning_key_with_default_message_extraction():
    """uses configured reasoning key with default message extraction"""
    assert _extract(
        {"content": "visible response", "reasoning": "provider reasoning"},
        ["reasoning"],
    ) == {"content": "visible response", "reasoning_content": "provider reasoning"}


def test_uses_the_first_configured_reasoning_key_with_a_string_value():
    """uses the first configured reasoning key with a string value"""
    reasoning_keys = ["reasoning_content", "reasoning"]

    assert _extract(
        {
            "content": "visible response",
            "reasoning_content": "provider reasoning_content",
            "reasoning": "vllm reasoning",
        },
        reasoning_keys,
    ) == {
        "content": "visible response",
        "reasoning_content": "provider reasoning_content",
    }

    assert _extract(
        {"content": "visible response", "reasoning": "vllm reasoning"},
        reasoning_keys,
    ) == {"content": "visible response", "reasoning_content": "vllm reasoning"}


@pytest.mark.skip(
    reason="Python chat-completion adapters do not implement the upstream "
    "custom message-extraction hook"
)
def test_uses_custom_message_extraction_when_configured():
    """uses custom message extraction when configured"""
    # No Python equivalent: the adapter layer has no messageExtraction hook.


def test_increases_the_default_temperature_on_a_semantic_retry_without_changing_user_config():
    """increases the default temperature on a semantic retry without changing user config"""
    runtime = ModelRuntime(
        {"modelName": "mock-model", "intent": "default", "temperature": None},
        adapter=get_model_adapter("default"),
    )
    retry_body = prepare_chat_completion(
        [], runtime, {"semanticRetryAttempt": 2}
    )["request_body"]
    assert retry_body["temperature"] == 0.2

    runtime_with_user_temperature = ModelRuntime(
        {"modelName": "mock-model", "intent": "default", "temperature": 0},
        adapter=get_model_adapter("default"),
    )
    user_temperature_body = prepare_chat_completion(
        [], runtime_with_user_temperature, {"semanticRetryAttempt": 1}
    )["request_body"]
    assert user_temperature_body["temperature"] == 0
