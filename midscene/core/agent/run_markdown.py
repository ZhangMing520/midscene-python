"""Markdown to aiAct prompt (upstream agent/run-markdown.ts)."""

import os
import re
from pathlib import Path
from typing import Any

from midscene.core.ai_model.shared.multimodal_prompt import prepare_reference_images

_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


_MARKDOWN_IMAGE_REFERENCE_PATTERN = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")


_MAX_MARKDOWN_IMAGES = 20


_REFERENCE_IMAGE_PREFIX = "参考图片"


_URL_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z\d+.-]*:")


def _markdown_to_ai_act_prompt(
    markdown: str, source_path: str | None = None
) -> str | dict[str, Any]:
    """Replace Markdown images with reference-image placeholders
    (upstream markdownToAiActPrompt)."""
    reference_match = _MARKDOWN_IMAGE_REFERENCE_PATTERN.search(markdown)
    if reference_match:
        raise ValueError(
            "runMarkdown does not support reference-style images; "
            "use direct image syntax instead."
        )
    images: list[dict[str, str]] = []

    def replace(match: "re.Match[str]") -> str:
        url = match.group(2)
        if not url:
            raise ValueError(
                f"Markdown image {_REFERENCE_IMAGE_PREFIX}-"
                f"{len(images) + 1:03d} is missing a URL."
            )
        name = f"{_REFERENCE_IMAGE_PREFIX}-{len(images) + 1:03d}"
        resolved = url
        if (
            source_path
            and not _URL_SCHEME_PATTERN.match(url)
            and not os.path.isabs(url)
        ):
            resolved = str(Path(source_path).resolve().parent / url)
        images.append({"name": name, "url": resolved})
        if len(images) > _MAX_MARKDOWN_IMAGES:
            raise ValueError(
                "runMarkdown supports at most "
                f"{_MAX_MARKDOWN_IMAGES} images, but found more."
            )
        return name

    prompt = _MARKDOWN_IMAGE_PATTERN.sub(replace, markdown)
    if not images:
        return markdown
    return {
        "prompt": prompt,
        "images": images,
        "convertHttpImage2Base64": True,
    }


async def _reference_images_from_prompt(task_prompt, force_base64=False):
    """Pull reference images out of a markdown-style prompt dict.

    Resolution happens once per aiAct and deduplicates URLs; System One (jev)
    requires data URLs, so force base64 there.
    """
    if isinstance(task_prompt, dict) and task_prompt.get("images"):
        return await prepare_reference_images(
            task_prompt["images"],
            bool(task_prompt.get("convertHttpImage2Base64", False)) or force_base64,
        )
    return None


async def run_markdown(
    agent,
    markdown_path: str,
    opt: dict[str, Any] | None = None,
) -> str | None:
    """Run a Markdown prompt file; images become reference images."""
    agent._check_not_destroyed()
    path = Path(markdown_path)
    markdown = path.read_text(encoding="utf-8")
    prompt = _markdown_to_ai_act_prompt(markdown, str(path))
    opt = dict(opt or {})
    opt.setdefault(
        "_internal_report_display",
        {"type": "Markdown", "prompt": path.name},
    )
    return await agent.ai_act(prompt, opt)
