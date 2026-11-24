"""Synced from upstream packages/core/tests/unit-test/multimodal-prompt.test.ts
and task-builder.test.ts (prompt snapping helpers)."""

from typing import Any

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
    async def test_prepare_user_prompt_preserves_text_order_and_names(
        self, monkeypatch
    ):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        calls: list[Any] = []

        def fake_resolve(image, convert_http):
            calls.append((image["url"], convert_http))
            return f"resolved:{image['url']}"

        monkeypatch.setattr(context_utils, "resolve_reference_image", fake_resolve)
        result = await context_utils.prepare_user_prompt(
            {
                "prompt": "find the button",
                "images": [
                    {"name": "first", "url": "a.png"},
                    {"name": "duplicate", "url": "a.png"},
                    {"name": "second", "url": "b.png"},
                ],
                "convertHttpImage2Base64": True,
            }
        )

        assert result == {
            "text": "find the button",
            "referenceImages": [
                {"name": "first", "url": "resolved:a.png"},
                {"name": "duplicate", "url": "resolved:a.png"},
                {"name": "second", "url": "resolved:b.png"},
            ],
        }
        assert sorted(calls) == [("a.png", True), ("b.png", True)]

    @pytest.mark.asyncio
    async def test_prepare_user_prompt_supports_string_prompts(self):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        result = await context_utils.prepare_user_prompt("just text")

        assert result == {"text": "just text", "referenceImages": []}

    @pytest.mark.asyncio
    async def test_prepare_user_prompt_defaults_http_conversion_to_false(
        self, monkeypatch
    ):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        captured: list[Any] = []
        monkeypatch.setattr(
            context_utils,
            "resolve_reference_image",
            lambda image, convert_http: captured.append(convert_http) or image["url"],
        )

        result = await context_utils.prepare_user_prompt(
            {"prompt": "p", "images": [{"name": "r", "url": "https://x/y.png"}]}
        )

        assert result["referenceImages"] == [{"name": "r", "url": "https://x/y.png"}]
        assert captured == [False]

    @pytest.mark.asyncio
    async def test_prepare_dedupes_urls(self, monkeypatch):
        from midscene.core.ai_model.shared import multimodal_prompt as context_utils

        calls: list[Any] = []

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
            lambda image, convert_http: (
                None if image["url"] == "missing.png" else image["url"]
            ),
        )
        result = await context_utils.prepare_reference_images(
            ["missing.png", "a.png"], convert_http=False
        )
        assert result == ["a.png"]
