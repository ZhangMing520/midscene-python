"""Locate prompt ordering DSL (upstream locate-prompt-order.ts).

Adapter definitions may reconfigure how the locate system instructions,
screenshot, task text and reference images are laid out across messages:

    system(instructions):userTogether(screenshot:task):userEach(references)

Every part must appear exactly once, and ``system`` may only contain the text
parts (instructions/task).
"""

import re
from collections.abc import Sequence
from typing import Any

from midscene.core.ai_model.shared.multimodal_prompt import resolve_reference_image

PARTS = ("instructions", "screenshot", "task", "references")
DEFAULT_LOCATE_PROMPT_ORDER = (
    "system(instructions):userTogether(screenshot:task):userEach(references)"
)

_TEXT_PARTS = ("instructions", "task")

REFERENCE_IMAGES_INTRO = (
    "Next, I will provide all the reference images. These reference images are "
    "supporting context only, not the current screenshot being evaluated, "
    "unless the task explicitly asks for comparison or matching."
)


def _invalid(order: str, reason: str) -> ValueError:
    return ValueError(f'Invalid locate promptOrder "{order}": {reason}')


def parse_locate_prompt_order(
    order: str = DEFAULT_LOCATE_PROMPT_ORDER,
) -> dict[str, Any]:
    """Parse a promptOrder string into ``{"groups": [...]}``."""
    remaining = set(PARTS)
    groups: list[dict[str, Any]] = []

    for group in re.split(r"(?<=\)):", order):
        match = re.match(r"^(system|userTogether|userEach)\(([^()]+)\)$", group)
        if not match:
            raise _invalid(
                order,
                "expected system(...), userTogether(...) or userEach(...), "
                f'got "{group}"',
            )
        mode, raw_parts = match.group(1), match.group(2)
        group_parts = raw_parts.split(":")
        for part in group_parts:
            if part not in remaining:
                raise _invalid(order, f'unknown or repeated part "{part}"')
            remaining.remove(part)
            if mode == "system" and part not in _TEXT_PARTS:
                raise _invalid(order, f'system cannot contain image part "{part}"')
        groups.append({"mode": mode, "parts": group_parts})

    if remaining:
        missing = ", ".join(part for part in PARTS if part in remaining)
        raise _invalid(order, f"missing {missing}")
    return {"groups": groups}


def build_locate_messages(
    order: dict[str, Any],
    locate_input: dict[str, Any],
) -> list[dict[str, Any]]:
    """Assemble locate messages by the parsed prompt order."""
    instructions = locate_input["instructions"]
    screenshot = locate_input["screenshot"]
    task = locate_input["task"]
    references = locate_input.get("references") or []
    values = {
        "instructions": instructions,
        "screenshot": screenshot,
        "task": task,
        "references": references,
    }

    messages: list[dict[str, Any]] = []
    for group in order["groups"]:
        if group["mode"] == "system":
            messages.append(
                {
                    "role": "system",
                    "content": "\n\n".join(values[part] for part in group["parts"]),
                }
            )
            continue

        expanded: list[dict[str, Any]] = []
        for part in group["parts"]:
            if part == "references":
                expanded.extend(references)
            elif part == "screenshot":
                expanded.append(
                    {"role": "user", "content": [{"type": "image", "url": screenshot}]}
                )
            else:
                expanded.append({"role": "user", "content": values[part]})

        if group["mode"] == "userEach":
            messages.extend(expanded)
        elif expanded:
            content: list[dict[str, Any]] = []
            for message in expanded:
                if isinstance(message["content"], str):
                    content.append({"type": "text", "text": message["content"]})
                else:
                    content.extend(message["content"])
            messages.append({"role": "user", "content": content})
    return messages


def prepared_reference_images_to_messages(
    reference_images: Sequence[dict[str, str]],
) -> list[dict[str, Any]]:
    """Reference-image user messages (upstream preparedReferenceImagesToMessages)."""
    if not reference_images:
        return []
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": REFERENCE_IMAGES_INTRO}]}
    ]
    for image in reference_images:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"this is the reference image named '{image['name']}'. "
                            "It is a reference image, not the current screenshot:"
                        ),
                    }
                ],
            }
        )
        messages.append(
            {"role": "user", "content": [{"type": "image", "url": image["url"]}]}
        )
    return messages


def multimodal_prompt_to_messages(prompt: Any) -> list[dict[str, Any]]:
    """Reference messages for a TUserPrompt's markdown images."""
    if not isinstance(prompt, dict) or not prompt.get("images"):
        return []
    convert_http = bool(prompt.get("convertHttpImage2Base64", False))
    prepared: list[dict[str, str]] = []
    for item in prompt["images"]:
        url = resolve_reference_image(item, convert_http)
        if url:
            name = item.get("name") if isinstance(item, dict) else None
            prepared.append({"name": name or "", "url": url})
    return prepared_reference_images_to_messages(prepared)
