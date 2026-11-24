"""Report image externalization/restoration (upstream dump/screenshot-restoration.ts).

Directory exports keep screenshots next to the report as relative paths;
rendering one back into a standalone HTML file must resolve (and inline) them.
"""

import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from midscene.core.dump.image_reference import (
    _DATA_URI_PATTERN,
    _is_image_string,
    normalize_image_url_ref,
    report_image_asset_path,
)
from midscene.core.dump.screenshot_store import normalize_screenshot_ref


class RestoredScreenshotReference:
    """Lazily resolved screenshot reference (upstream restored object shape)."""

    def __init__(
        self,
        source_ref: dict[str, Any],
        resolve_image: Callable[[dict[str, Any]], str],
    ) -> None:
        self._source_ref = source_ref
        self._resolve_image = resolve_image
        self._resolved: str | None = None

    @property
    def base64(self) -> str:
        if self._resolved is None:
            self._resolved = self._resolve_image(self._source_ref)
        return self._resolved

    @property
    def captured_at(self) -> int | None:
        return self._source_ref.get("capturedAt")

    @property
    def source_ref(self) -> dict[str, Any]:
        return dict(self._source_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base64": self.base64,
            "capturedAt": self.captured_at,
            "sourceRef": self.source_ref,
        }


def create_inline_image_resolver(
    images: dict[str, str],
) -> Callable[[dict[str, Any]], str]:
    """Create a resolver that fails loudly when an inline asset is absent."""

    def resolve(ref: dict[str, Any]) -> str:
        image = images.get(ref["id"])
        if not image:
            raise ValueError(f'Missing inline report image "{ref["id"]}"')
        return image

    return resolve


def restore_image_references(
    data: Any,
    resolve_image: Callable[[dict[str, Any]], str],
) -> Any:
    """Recursively restore image references in parsed data.

    Screenshot refs become lazy objects exposing ``base64``/``capturedAt``/
    ``sourceRef``; prompt-image URL refs become their resolved URL string.
    """
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return [restore_image_references(item, resolve_image) for item in data]
    if isinstance(data, dict):
        image_url_ref = normalize_image_url_ref(data)
        if image_url_ref is not None:
            return resolve_image(image_url_ref)

        screenshot_ref = normalize_screenshot_ref(data)
        if screenshot_ref is not None:
            return RestoredScreenshotReference(screenshot_ref, resolve_image)

        return {
            key: restore_image_references(value, resolve_image)
            for key, value in data.items()
        }
    return data


def restore_report_image_references(data: Any, report_url: str) -> Any:
    """Restore file-backed report images to browser-resolvable URLs."""

    def resolve_report_image(ref: dict[str, Any]) -> str:
        return urljoin(report_url, report_image_asset_path(ref))

    return restore_image_references(data, resolve_report_image)


def _save_image(
    value: str,
    screenshots_dir: Path,
    written: set,
    state: dict[str, int],
    prefix: str,
) -> dict[str, Any]:
    data_uri = _DATA_URI_PATTERN.match(value)
    if data_uri:
        raw = data_uri.group(2)
        extension = (
            "jpg"
            if data_uri.group(1).lower() in ("jpeg", "jpg")
            else data_uri.group(1).lower()
        )
    else:
        raw = value
        extension = "png"
    state["counter"] += 1
    name = f"{prefix}-{state['counter']:03d}.{extension}"
    if name not in written:
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        (screenshots_dir / name).write_bytes(base64.b64decode(raw))
        written.add(name)
    return {
        "id": name.rsplit(".", 1)[0],
        "storage": "file",
        "path": f"./screenshots/{name}",
    }


def _externalize_images(
    value: Any,
    key: str | None,
    screenshots_dir: Path,
    written: set,
    state: dict[str, int],
    prefix: str,
) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _externalize_images(
                item_value, item_key, screenshots_dir, written, state, prefix
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [
            _externalize_images(item, key, screenshots_dir, written, state, prefix)
            for item in value
        ]
    if isinstance(value, str) and _is_image_string(value, key):
        return _save_image(value, screenshots_dir, written, state, prefix)
    return value


def _inline_file_images(
    value: Any,
    base_dirs: list[Path],
    cache: dict[str, str] | None = None,
) -> Any:
    """Embed {storage: 'file'} images as data URLs.

    Directory exports keep screenshots next to the report as relative paths;
    rendering one back into a standalone HTML file must resolve (and inline)
    them, otherwise the exported report shows broken images.
    """
    if cache is None:
        cache = {}
    if isinstance(value, dict):
        if value.get("storage") == "file" and isinstance(value.get("path"), str):
            relative = value["path"]
            if relative in cache:
                return cache[relative]
            for base in base_dirs:
                root = base.resolve()
                candidate = (root / relative).resolve()
                if not candidate.is_file():
                    continue
                try:
                    candidate.relative_to(root)
                except ValueError:
                    continue
                suffix = candidate.suffix.lstrip(".").lower() or "png"
                mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
                data = base64.b64encode(candidate.read_bytes()).decode("ascii")
                cache[relative] = f"data:{mime};base64,{data}"
                return cache[relative]
            return value
        return {
            item_key: _inline_file_images(item_value, base_dirs, cache)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_inline_file_images(item, base_dirs, cache) for item in value]
    return value


__all__ = [
    "RestoredScreenshotReference",
    "_externalize_images",
    "_inline_file_images",
    "_save_image",
    "create_inline_image_resolver",
    "restore_image_references",
    "restore_report_image_references",
]
