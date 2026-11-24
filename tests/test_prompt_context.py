"""Synced from upstream packages/core/tests/unit-test/prompt-context.test.ts."""

from midscene.core.agent.prompt_context import (
    build_locate_prompt_with_context,
    build_prompt_with_context,
    render_ai_context,
)


def test_returns_the_original_string_prompt_when_context_is_undefined_or_blank():
    """returns the original string prompt when context is undefined or blank"""
    assert build_prompt_with_context("Click submit", None) == "Click submit"
    assert build_prompt_with_context("Click submit", "   ") == "Click submit"


def test_renders_and_prepends_context_to_string_prompts():
    """renders and prepends context to string prompts"""
    assert (
        build_prompt_with_context("Click submit", "Use buyer checkout rules.")
        == "<CONTEXT>\nUse buyer checkout rules.\n</CONTEXT>\n\nClick submit"
    )


def test_preserves_multimodal_prompt_fields_while_updating_prompt_text():
    """preserves multimodal prompt fields while updating prompt text"""
    assert build_prompt_with_context(
        {
            "prompt": "Click the target shown in the reference image.",
            "images": [{"name": "target", "url": "./target.png"}],
            "convertHttpImage2Base64": True,
        },
        "Use mobile layout.",
    ) == {
        "prompt": (
            "<CONTEXT>\nUse mobile layout.\n</CONTEXT>\n\n"
            "Click the target shown in the reference image."
        ),
        "images": [{"name": "target", "url": "./target.png"}],
        "convertHttpImage2Base64": True,
    }


def test_renders_context_and_locate_target_in_explicit_tags():
    """renders context and locate target in explicit tags"""
    assert build_locate_prompt_with_context(
        "Favorite button",
        "The favorite button is the star icon in the bottom-right corner.",
    ) == (
        "<CONTEXT>\n"
        "The favorite button is the star icon in the bottom-right corner.\n"
        "</CONTEXT>\n\n"
        "<LOCATE_TARGET>\nFavorite button\n</LOCATE_TARGET>"
    )


def test_preserves_multimodal_fields_while_wrapping_the_prompt_text():
    """preserves multimodal fields while wrapping the prompt text"""
    assert build_locate_prompt_with_context(
        {
            "prompt": "Favorite button",
            "images": [{"name": "target", "url": "./target.png"}],
        },
        "Use the mobile layout.",
    ) == {
        "prompt": (
            "<CONTEXT>\nUse the mobile layout.\n</CONTEXT>\n\n"
            "<LOCATE_TARGET>\nFavorite button\n</LOCATE_TARGET>"
        ),
        "images": [{"name": "target", "url": "./target.png"}],
    }


def test_renders_every_resolved_context_with_the_same_model_facing_structure():
    """renders every resolved context with the same model-facing structure"""
    assert render_ai_context("Shared business rules.") == (
        "<CONTEXT>\nShared business rules.\n</CONTEXT>"
    )


def test_preserves_the_distinction_between_omitted_and_explicitly_blank_context():
    """preserves the distinction between omitted and explicitly blank context"""
    assert render_ai_context(None) is None
    assert render_ai_context("") == ""
    assert render_ai_context("   ") == ""
