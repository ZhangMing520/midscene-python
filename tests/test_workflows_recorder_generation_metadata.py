"""Synced from upstream packages/core/tests/unit-test/workflows/recorder-generation/metadata.test.ts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.ai_model.workflows.recorder_generation.metadata import (
    generate_recorder_session_metadata,
)


@pytest.mark.asyncio
async def test_omits_fallback_audit_chains_before_building_metadata_prompts():
    """omits fallback audit chains before building metadata prompts"""
    long_error = "verify failed: " + "x" * 5000

    mocked_model_config = {
        "modelName": "mock",
        "modelDescription": "mock",
        "intent": "default",
        "slot": "default",
    }
    model_runtime = SimpleNamespace(config=mocked_model_config)

    mock_response = {
        "content": {
            "title": "Example Recording",
            "description": "The user completed an example workflow.",
        },
        "contentString": (
            '{"title":"Example Recording",'
            '"description":"The user completed an example workflow."}'
        ),
        "usage": None,
    }
    mock_call = AsyncMock(return_value=mock_response)

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.metadata."
        "call_ai_with_object_response",
        new=mock_call,
    ):
        await generate_recorder_session_metadata(
            {
                "platformId": "web",
                "label": "Web",
                "values": {"url": "https://example.com"},
            },
            [
                {
                    "type": "click",
                    "actionType": "Tap",
                    "timestamp": 1000,
                    "semantic": {
                        "source": "recorderAI",
                        "status": "ready",
                        "elementDescription": "Submit button",
                        "error": long_error,
                        "fallbackFrom": {
                            "source": "aiDescribe",
                            "status": "failed",
                            "error": long_error,
                            "fallbackFrom": {
                                "source": "heuristic",
                                "status": "failed",
                                "error": long_error,
                            },
                        },
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "click-with-long-semantic",
                }
            ],
            model_runtime,
            max_screenshots=0,
        )

    prompt = mock_call.call_args.args[0]
    user_message = prompt[1]
    assert "role" in user_message
    content = user_message["content"]
    text = (
        "\n".join(
            part["text"] for part in content if part.get("type") == "text"
        )
        if isinstance(content, list)
        else ""
    )

    assert '"error": "verify failed:' in text
    assert "[truncated" in text
    assert '"fallbackFrom"' not in text
    assert '"source": "heuristic"' not in text
    assert len(text) < 10000
