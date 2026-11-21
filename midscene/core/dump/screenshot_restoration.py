"""Report image externalization/restoration (upstream dump/screenshot-restoration.ts).

Directory exports keep screenshots next to the report as relative paths;
rendering one back into a standalone HTML file must resolve (and inline) them.
"""

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

from midscene.core.dump.image_reference import _DATA_URI_PATTERN, _is_image_string


def _save_image(
    value: str,
    screenshots_dir: Path,
    written: set,
    state: Dict[str, int],
    prefix: str,
) -> Dict[str, Any]:
    data_uri = _DATA_URI_PATTERN.match(value)
    if data_uri:
        raw = data_uri.group(2)
        extension = "jpg" if data_uri.group(1).lower() in ("jpeg", "jpg") else data_uri.group(1).lower()
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
    key: Optional[str],
    screenshots_dir: Path,
    written: set,
    state: Dict[str, int],
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
    base_dirs: List[Path],
    cache: Optional[Dict[str, str]] = None,
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
                mime = (
                    "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
                )
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
    "_externalize_images",
    "_inline_file_images",
    "_save_image",
]
