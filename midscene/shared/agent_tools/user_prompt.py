"""Compose user prompts with reference images (upstream user-prompt.ts)."""

from typing import Any

from midscene.shared.agent_tools.types import schema_field

PromptReferenceImage = dict[str, str]
UserPromptLike = str | dict[str, Any]


def _normalize_string_list(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        trimmed = raw.strip()
        return [trimmed] if trimmed else []
    if isinstance(raw, list):
        values: list[str] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str):
                raise ValueError(f"{field_name}[{index}]: expected a string.")
            values.append(item.strip())
        return values
    raise ValueError(
        f"{field_name}: expected a string or string array, got {type(raw).__name__}."
    )


def _compose_images(image: Any, image_name: Any) -> list[PromptReferenceImage]:
    urls = _normalize_string_list(image, "image")
    names = _normalize_string_list(image_name, "imageName")
    if len(urls) != len(names):
        raise ValueError(
            "image/imageName: expected the same number of --image and "
            f"--image-name values, got {len(urls)} image(s) and "
            f"{len(names)} image name(s)."
        )
    return [{"name": name, "url": url} for name, url in zip(names, urls, strict=False)]


def _coerce_boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        lowered = trimmed.lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        raise ValueError(
            'convertHttpImage2Base64: expected "true", "false", "1", or '
            f'"0"; got {value!r}.'
        )
    raise ValueError(
        f"convertHttpImage2Base64: expected a boolean, got {type(value).__name__}."
    )


def compose_user_prompt(
    prompt: str,
    image: Any = None,
    image_name: Any = None,
    convert_http_image_to_base64: Any = None,
) -> UserPromptLike:
    images = _compose_images(image, image_name)
    convert_flag = _coerce_boolean(convert_http_image_to_base64)

    if not images and convert_flag is None:
        return prompt

    payload: dict[str, Any] = {"prompt": prompt}
    if images:
        payload["images"] = images
    if convert_flag is not None:
        payload["convertHttpImage2Base64"] = convert_flag
    return payload


PROMPT_INPUT_EXTRA_SCHEMA: dict[str, dict[str, Any]] = {
    "image": schema_field(
        "string | string[]",
        "Reference image URL/path. Repeat --image for multiple images.",
        optional=True,
    ),
    "imageName": schema_field(
        "string | string[]",
        "Reference image name. Repeat --image-name; must align with --image order.",
        optional=True,
    ),
    "convertHttpImage2Base64": schema_field(
        "boolean | string",
        "If true, convert http(s) image URLs to base64 before sending to the model.",
        optional=True,
    ),
}


__all__ = ["PROMPT_INPUT_EXTRA_SCHEMA", "UserPromptLike", "compose_user_prompt"]
