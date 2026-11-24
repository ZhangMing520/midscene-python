"""Synced from upstream
``packages/core/tests/unit-test/service-caller-streaming.test.ts``
(``reads usage after finish_reason and completes only after the stream ends``)."""

from typing import Any

import pytest


async def _stream_lines(lines):
    for line in lines:
        yield line


@pytest.mark.asyncio
async def test_reads_usage_after_finish_reason_and_completes_only_after_the_stream_ends():
    from midscene.core.ai_model.service_caller.model_call import _aggregate_stream_lines

    chunks: list[dict[str, Any]] = []
    result = await _aggregate_stream_lines(
        _stream_lines(
            [
                'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                'data: {"choices":[{"delta":{"content":"lo"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":1,'
                '"completion_tokens":2,"total_tokens":3}}',
                "data: [DONE]",
            ]
        ),
        chunks.append,
    )

    assert result["content"] == "Hello"
    assert [chunk["content"] for chunk in chunks[:-1]] == ["Hel", "lo"]
    assert chunks[-1]["isComplete"] is True
    assert chunks[-1]["accumulated"] == "Hello"
    assert chunks[-1]["usage"]["total_tokens"] == 3
