"""Synced from upstream packages/core/tests/unit-test/multimodal-prompt.test.ts
and task-builder.test.ts (prompt snapping helpers)."""

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
