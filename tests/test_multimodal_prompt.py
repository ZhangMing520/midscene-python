"""Synced from upstream packages/core/tests/unit-test/multimodal-prompt.test.ts
and task-builder.test.ts (prompt snapping helpers)."""

from typing import Any, List

import pytest

from midscene.core.common import (
    get_readable_time_string,
    user_prompt_to_multimodal_prompt,
)


def test_prepares_multimodal_prompt_and_readable_time_from_user_prompt():
    assert user_prompt_to_multimodal_prompt("hi") is None
    assert user_prompt_to_multimodal_prompt({"prompt": "hi"}) is None
    assert user_prompt_to_multimodal_prompt(
        {"prompt": "hi", "images": [{"name": "a", "url": "b"}]}
    ) == {
        "images": [{"name": "a", "url": "b"}],
        "convertHttpImage2Base64": False,
    }
    assert get_readable_time_string("YYYY-MM-DD", 0).endswith("(YYYY-MM-DD)")


class TestReferenceImages:
    @pytest.mark.asyncio
    async def test_prepare_dedupes_urls(self, monkeypatch):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        calls: List[Any] = []

        def fake_resolve(image, convert_http):
            calls.append((image["url"], convert_http))
            return f"resolved:{image['url']}"

        monkeypatch.setattr(context_utils, "resolve_reference_image", fake_resolve)
        result = await context_utils.prepare_reference_images(
            [{"url": "a.png"}, "a.png", "b.png"], convert_http=True
        )

        assert result == ["resolved:a.png", "resolved:a.png", "resolved:b.png"]
        assert sorted(calls) == [("a.png", True), ("b.png", True)]

    @pytest.mark.asyncio
    async def test_prepare_drops_unresolved(self, monkeypatch):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        monkeypatch.setattr(
            context_utils,
            "resolve_reference_image",
            lambda image, convert_http: None
            if image["url"] == "missing.png"
            else image["url"],
        )
        result = await context_utils.prepare_reference_images(
            ["missing.png", "a.png"], convert_http=False
        )
        assert result == ["a.png"]

