"""Report reading, splitting and publication helpers (upstream core/src/report*.ts).

The image helpers now live in `midscene.core.dump.image_reference` and
`midscene.core.dump.screenshot_restoration`; this module keeps
`write_report_html` and re-exports the moved helpers for existing imports.
"""

from typing import Any, Dict, Optional
from pathlib import Path
from loguru import logger

from midscene.shared.env import get_midscene_run_dir

from midscene.core.report_html_template import (
    render_report_html,
)
from midscene.core.dump.image_reference import (
    _BASE64_PATTERN,
    _DATA_URI_PATTERN,
    _IMAGE_KEYS,
    _is_image_string,
)
from midscene.core.dump.screenshot_restoration import (
    _externalize_images,
    _inline_file_images,
    _save_image,
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


__all__ = [
    "_BASE64_PATTERN",
    "_DATA_URI_PATTERN",
    "_IMAGE_KEYS",
    "_externalize_images",
    "_inline_file_images",
    "_is_image_string",
    "_save_image",
    "write_report_html",
]
