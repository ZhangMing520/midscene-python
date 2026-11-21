"""Report reading, splitting and publication helpers (upstream core/src/report*.ts)."""

from typing import Any, Dict, List, Optional
import re
import base64
from pathlib import Path
from loguru import logger

from midscene.shared.env import get_midscene_run_dir

from midscene.core.report_html_template import (
    render_report_html,
)

def write_report_html(
    dump: Dict[str, Any],
    file_name: Optional[str] = None,
    run_dir: Optional[str] = None,
) -> Optional[str]:
    """Write `<midscene_run>/report/<name>.html` rendering the dump."""
    try:
        report_dir = Path(run_dir or get_midscene_run_dir("report"))
        report_dir.mkdir(parents=True, exist_ok=True)
        if not file_name:
            import time as _time
            import uuid as _uuid

            file_name = (
                f"report-{_time.strftime('%Y-%m-%d_%H-%M-%S')}-{_uuid.uuid4().hex[:8]}"
            )
        name = file_name.rsplit(".", 1)[0] if file_name.lower().endswith((".html", ".json")) else file_name

        html = render_report_html(dump, name)
        path = report_dir / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        logger.info(f"Midscene - HTML report written: {path}")
        return str(path)
    except Exception as e:
        logger.warning(f"failed to write HTML report: {e}")
        return None


_DATA_URI_PATTERN = re.compile(
    r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.*)$", re.IGNORECASE | re.DOTALL
)


_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")


_IMAGE_KEYS = {
    "base64",
    "imagebase64",
    "screenshot",
    "screenshots",
    "screenshot_base64",
}


def _is_image_string(value: str, key: Optional[str]) -> bool:
    if value.startswith("data:image/"):
        return True
    if not key or key.lower() not in _IMAGE_KEYS:
        return False
    return bool(_BASE64_PATTERN.match(value))


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


