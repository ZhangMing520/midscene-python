"""Generic core utilities (upstream core/src/utils.ts).

The Python SDK has no browser/worker runtimes, so the `ifInBrowser` /
`ifInWorker` branches collapse to the node-like behavior. Report HTML helpers
live in `midscene.core.dump.html_utils` and are re-exported here.
"""

import json
import os
import time
import uuid
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from midscene.core.dump.html_utils import (
    anti_escape_script_tag,
    escape_script_tag,
    get_report_tpl,
    insert_content_before_closing_html,
    insert_script_before_closing_html,
    report_html_content,
    write_dump_report,
    write_log_file,
)
from midscene.shared.env.constants import MIDSCENE_CACHE

MIDSCENE_DEBUG_MODE = "MIDSCENE_DEBUG_MODE"

GROUPED_ACTION_DUMP_FILE_EXT = "web-dump.json"


def _uuid() -> str:
    return uuid.uuid4().hex


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def process_cache_config(cache: Any, cache_id: str) -> Any:
    """Normalize cache config with env fallback (upstream processCacheConfig)."""
    if cache is not None:
        if cache is False:
            return False
        if cache is True:
            return {"id": cache_id}
        if isinstance(cache, dict):
            if not cache.get("id"):
                return {**cache, "id": cache_id}
            return cache

    if _env_truthy(MIDSCENE_CACHE) and cache_id:
        return {"id": cache_id}
    return None


def get_tmp_dir() -> Optional[str]:
    """Return a package-named temp directory, or None when unavailable."""
    try:
        import midscene
        from tempfile import gettempdir

        name = getattr(midscene, "__package_name__", None) or "midscene"
        path = Path(gettempdir()) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception:  # noqa: BLE001 - temp helpers never raise upstream
        return None


def get_tmp_file(file_ext_without_dot: str) -> Optional[str]:
    tmp_dir = get_tmp_dir()
    if tmp_dir is None:
        return None
    return str(Path(tmp_dir) / f"{_uuid()}.{file_ext_without_dot}")


def overlapped(container: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Whether two rects overlap (upstream overlapped)."""
    return (
        container["left"] < target["left"] + target["width"]
        and container["left"] + container["width"] > target["left"]
        and container["top"] < target["top"] + target["height"]
        and container["top"] + container["height"] > target["top"]
    )


async def sleep(ms: float) -> None:
    await asyncio.sleep(ms / 1000.0)


def replacer_for_page_object(_key: str, value: Any) -> Any:
    """JSON replacer that serializes page objects and ScreenshotItems."""
    class_name = type(value).__name__
    if class_name in ("Page", "Browser"):
        return f"[{class_name} object]"
    if value is not None and callable(getattr(value, "toSerializable", None)):
        return value.toSerializable()
    return value


def stringify_dump_data(data: Any, indents: Optional[int] = None) -> str:
    return json.dumps(data, default=replacer_for_page_object, indent=indents)


def get_version() -> str:
    import midscene

    return midscene.__version__


def debug_log(*message: Any) -> None:
    """Log only when MIDSCENE_DEBUG_MODE is set (upstream debugLog)."""
    if os.environ.get(MIDSCENE_DEBUG_MODE):
        logger.info("[Midscene] " + " ".join(str(item) for item in message))


def format_timestamp(format: str = "YYYY-MM-DD HH:mm:ss", timestamp: Optional[float] = None) -> str:
    value = (
        time.localtime(timestamp / 1000.0) if timestamp is not None else time.localtime()
    )
    replacements = {
        "YYYY": str(value.tm_year),
        "MM": f"{value.tm_mon:02d}",
        "DD": f"{value.tm_mday:02d}",
        "HH": f"{value.tm_hour:02d}",
        "mm": f"{value.tm_min:02d}",
        "ss": f"{value.tm_sec:02d}",
    }
    result = format
    for token, replacement in replacements.items():
        result = result.replace(token, replacement)
    return f"{result} ({format})"


__all__ = [
    "GROUPED_ACTION_DUMP_FILE_EXT",
    "anti_escape_script_tag",
    "debug_log",
    "escape_script_tag",
    "format_timestamp",
    "get_report_tpl",
    "get_tmp_dir",
    "get_tmp_file",
    "get_version",
    "insert_content_before_closing_html",
    "insert_script_before_closing_html",
    "overlapped",
    "process_cache_config",
    "report_html_content",
    "replacer_for_page_object",
    "sleep",
    "stringify_dump_data",
    "write_dump_report",
    "write_log_file",
]
