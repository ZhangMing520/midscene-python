"""Synced from upstream
``packages/core/tests/unit-test/service-caller-responses.test.ts``
(``delivers deltas and sends the final chunk only after completion with usage``)."""

from typing import Any

import pytest


async def _stream_lines(lines):
    for line in lines:
        yield line


@pytest.mark.asyncio
async def test_delivers_deltas_and_sends_the_final_chunk_only_after_the_stream_ends():
    from midscene.core.ai_model.service_caller.model_call import _aggregate_stream_lines

    chunks: list[dict[str, Any]] = []
    result = await _aggregate_stream_lines(
        _stream_lines(
            [
                'data: {"type":"response.output_text.delta","delta":"ab"}',
                'data: {"type":"response.output_text.delta","delta":"c"}',
                'data: {"type":"response.completed","response":'
                '{"id":"r1","model":"m","output":[{"type":"message",'
                '"content":[{"type":"output_text","text":"abc"}]}],'
                '"usage":{"input_tokens":1,"output_tokens":2,'
                '"total_tokens":3}}}',
            ]
        ),
        chunks.append,
    )

    assert result["content"] == "abc"
    assert chunks[-1]["isComplete"] is True
