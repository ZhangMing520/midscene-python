"""Synced from upstream packages/core/tests/unit-test/prompt/describe.test.ts."""

import pytest

from midscene.core.ai_model.prompt.describe import element_describer_instruction


@pytest.fixture(autouse=True)
def _english_prompt(monkeypatch):
    monkeypatch.setenv("MIDSCENE_PREFERRED_LANGUAGE", "English")


@pytest.mark.skip(
    reason="upstream uses toMatchSnapshot(); the Python port has no stored "
    "prompt snapshot to compare against"
)
def test_should_return_the_correct_instruction():
    pass


def test_uses_description_only_schema():
    instruction = element_describer_instruction()

    assert "ring with a crosshair" in instruction
    assert '"description"' in instruction
    assert '"description": "unique element identifier"' in instruction
    assert '"target": "the smallest indicated UI part itself' not in instruction
    assert '"primitive": "text | icon | arrow' not in instruction
    assert "OBSERVE IN THIS ORDER:\n1. Target first:" in instruction


def test_documents_dropdown_and_option_targets_distinctly_from_inputs_and_icons():
    instruction = element_describer_instruction()

    assert (
        'use primitive "dropdown" and describe that dropdown/select control'
        in instruction
    )
    assert 'use primitive "option" for selectable list options' in instruction
    assert (
        'Only use primitive "icon" or "arrow" when the marker center directly '
        "overlaps the real glyph strokes" in instruction
    )
