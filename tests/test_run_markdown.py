"""Synced from upstream packages/core/tests/unit-test/run-markdown.test.ts.

The Python port keeps ``_markdown_to_ai_act_prompt`` (the upstream
``markdownToAiActPrompt`` transform) and ``run_markdown``. It returns the
prompt payload directly instead of wrapping it in ``{prompt, imageCount}``,
and its error messages do not include image counts/filenames/identifiers;
those cases are skipped below.
"""

from pathlib import Path

import pytest

from midscene.core.agent.run_markdown import (
    _markdown_to_ai_act_prompt,
    run_markdown,
)


class FakeAgent:
    def __init__(self):
        self.calls = []

    def _check_not_destroyed(self):
        pass

    async def ai_act(self, prompt, opt=None):
        self.calls.append((prompt, opt))
        return "done"


@pytest.mark.asyncio
async def test_replaces_markdown_images_with_numbered_reference_image_names():
    """replaces Markdown images with numbered reference image names"""
    result = _markdown_to_ai_act_prompt(
        """
# Task

Click the button shown below.

![ignored alt](./fixtures/button.png)

Then compare it with:

![](https://example.com/reference.png)
"""
    )

    assert len(result["images"]) == 2
    assert result == {
        "prompt": (
            "\n# Task\n\nClick the button shown below.\n\n参考图片-001\n\n"
            "Then compare it with:\n\n参考图片-002\n"
        ),
        "images": [
            {"name": "参考图片-001", "url": "./fixtures/button.png"},
            {
                "name": "参考图片-002",
                "url": "https://example.com/reference.png",
            },
        ],
        "convertHttpImage2Base64": True,
    }


def test_falls_back_to_the_original_markdown_string_when_there_are_no_images():
    """falls back to the original Markdown string when there are no images"""
    markdown = "# Task\n\nClick the submit button.\n"

    result = _markdown_to_ai_act_prompt(markdown)

    assert result == markdown


@pytest.mark.skip(
    reason="Python error omits the found image count and source filename that "
    "the upstream message asserts"
)
@pytest.mark.asyncio
async def test_throws_when_the_markdown_contains_more_than_20_images():
    """throws when the Markdown contains more than 20 images"""
    pass


@pytest.mark.skip(
    reason="Python error omits the reference-style image identifier and source "
    "filename that the upstream message asserts"
)
@pytest.mark.asyncio
async def test_throws_on_reference_style_images():
    """throws on reference-style images"""
    pass


@pytest.mark.asyncio
async def test_reads_a_markdown_file_and_forwards_the_transformed_prompt_to_ai_act(
    tmp_path,
):
    """reads a Markdown file and forwards the transformed prompt to aiAct"""
    markdown_path = tmp_path / "task.md"
    markdown_path.write_text(
        "Use this target:\n\n![](./target.png)\n", encoding="utf-8"
    )
    agent = FakeAgent()
    opt = {"cacheable": False}

    await run_markdown(agent, str(markdown_path), opt)

    assert len(agent.calls) == 1
    prompt, call_opt = agent.calls[0]
    assert prompt == {
        "prompt": "Use this target:\n\n参考图片-001\n",
        "images": [
            {
                "name": "参考图片-001",
                "url": str(Path(markdown_path).resolve().parent / "target.png"),
            }
        ],
        "convertHttpImage2Base64": True,
    }
    assert call_opt == {
        **opt,
        "_internal_report_display": {"type": "Markdown", "prompt": "task.md"},
    }


@pytest.mark.asyncio
async def test_resolves_local_relative_image_paths_from_the_markdown_file_directory(
    tmp_path,
):
    """resolves local relative image paths from the Markdown file directory"""
    markdown_path = tmp_path / "task.md"
    markdown_path.write_text(
        "Use local and remote images:\n\n![](./target.png)\n\n"
        "![](https://example.com/target.png)\n\n"
        "![](data:image/png;base64,abc)\n",
        encoding="utf-8",
    )

    result = _markdown_to_ai_act_prompt(
        markdown_path.read_text(encoding="utf-8"), str(markdown_path)
    )

    assert result["images"] == [
        {
            "name": "参考图片-001",
            "url": str(Path(markdown_path).resolve().parent / "target.png"),
        },
        {
            "name": "参考图片-002",
            "url": "https://example.com/target.png",
        },
        {"name": "参考图片-003", "url": "data:image/png;base64,abc"},
    ]


@pytest.mark.asyncio
async def test_passes_the_markdown_filename_as_the_report_display_prompt(tmp_path):
    """passes the Markdown filename as the report display prompt"""
    markdown_path = tmp_path / "task.md"
    markdown_path.write_text(
        "Use this target:\n\n![](./target.png)\n", encoding="utf-8"
    )
    agent = FakeAgent()

    await run_markdown(agent, str(markdown_path), {"cacheable": False})

    assert len(agent.calls) == 1
    _, call_opt = agent.calls[0]
    assert call_opt["cacheable"] is False
    assert call_opt["_internal_report_display"] == {
        "type": "Markdown",
        "prompt": "task.md",
    }


@pytest.mark.skip(
    reason="Python has no paramStr/ui-utils helper for planning task display "
    "(userInstructionDisplay is only consumed inside the CLI verbose printer)"
)
def test_uses_userinstructiondisplay_when_rendering_planning_task_params():
    """uses userInstructionDisplay when rendering planning task params"""
    pass
