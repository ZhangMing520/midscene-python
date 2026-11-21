"""Generic core utilities (upstream core/src/utils.ts).

The Python SDK has no browser/worker runtimes, so the `ifInBrowser` /
`ifInWorker` branches collapse to the node-like behavior.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

from loguru import logger

from midscene.core.constants import IS_REPORT_BUILD
from midscene.core.report_html_template import _TEMPLATE
from midscene.shared.env import get_midscene_run_dir
from midscene.shared.env.constants import MIDSCENE_CACHE

MIDSCENE_DEBUG_MODE = "MIDSCENE_DEBUG_MODE"

GROUPED_ACTION_DUMP_FILE_EXT = "web-dump.json"

_report_initialized: Dict[str, bool] = {}
_report_group_ids: Dict[str, str] = {}


def _uuid() -> str:
    return uuid.uuid4().hex


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def escape_script_tag(value: str) -> str:
    """Escape angle brackets so inline JSON cannot break the host page."""
    return value.replace("<", "__midscene_lt__").replace(">", "__midscene_gt__")


def anti_escape_script_tag(value: str) -> str:
    """Reverse `escape_script_tag`."""
    return value.replace("__midscene_lt__", "<").replace("__midscene_gt__", ">")


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


def get_report_tpl() -> str:
    """Return the report HTML shell used for inline dump injection."""
    if IS_REPORT_BUILD:
        return ""
    return _TEMPLATE


def insert_content_before_closing_html(html: str, content: str) -> str:
    """Insert content before `</html>`, or append when the tag is missing."""
    index = html.rfind("</html>")
    if index == -1:
        return html + content
    return f"{html[:index]}{content}\n{html[index:]}"


def insert_script_before_closing_html(file_path: str, script_content: str) -> None:
    """Insert a script tag before `</html>` in an existing HTML file."""
    path = Path(file_path)
    html = path.read_text(encoding="utf-8")
    if "</html>" not in html:
        raise RuntimeError(f"No </html> found in file: {file_path}")
    path.write_text(
        insert_content_before_closing_html(html, f"{script_content}"),
        encoding="utf-8",
    )


def _report_script_tag(dump_data: Union[str, Dict[str, Any]], group_id: str) -> str:
    close_tag = "</script>"
    if isinstance(dump_data, str):
        attributes = f'data-group-id="{group_id}"'
        dump_string = dump_data
    else:
        dump_string = str(dump_data.get("dumpString", ""))
        attributes = " ".join(
            f'{key}="{value}"'
            for key, value in (dump_data.get("attributes") or {}).items()
            if value is not None
        )
    return (
        '<script type="midscene_web_dump" type="application/json" '
        f"{attributes}>\n{escape_script_tag(dump_string)}\n{close_tag}"
    )


def report_html_content(
    dump_data: Union[str, Dict[str, Any]],
    report_path: Optional[str] = None,
    append_report: bool = False,
    with_tpl: bool = True,
) -> str:
    """Embed a dump into the report template (upstream reportHTMLContent)."""
    if IS_REPORT_BUILD:
        return ""

    tpl = get_report_tpl() if with_tpl else ""
    if with_tpl and not tpl:
        logger.warning("reportTpl is not set, will not write report")
        return ""

    write_to_file = bool(report_path)
    if not report_path or not append_report:
        group_id = _uuid()
    else:
        group_id = _report_group_ids.get(report_path) or _uuid()
        _report_group_ids[report_path] = group_id

    dump_content = _report_script_tag(dump_data, group_id)

    if write_to_file:
        if not append_report:
            Path(report_path).write_text(
                insert_content_before_closing_html(tpl, dump_content),
                encoding="utf-8",
            )
            return report_path
        if not _report_initialized.get(report_path):
            Path(report_path).write_text(tpl, encoding="utf-8")
            _report_initialized[report_path] = True
        insert_script_before_closing_html(report_path, dump_content)
        return report_path

    return insert_content_before_closing_html(tpl, dump_content)


def write_dump_report(
    file_name: str,
    dump_data: Union[str, Dict[str, Any]],
    append_report: bool = False,
) -> Optional[str]:
    """Write `<midscene_run>/report/<name>.html` (upstream writeDumpReport)."""
    report_path = str(Path(get_midscene_run_dir("report")) / f"{file_name}.html")
    report_html_content(dump_data, report_path, append_report)

    if os.environ.get("MIDSCENE_DEBUG_LOG_JSON"):
        json_path = f"{report_path}.json"
        data = json.loads(dump_data) if isinstance(dump_data, str) else dump_data
        Path(json_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Midscene - dump file written: {json_path}")
    return report_path


def write_log_file(opts: Dict[str, Any]) -> Optional[str]:
    """Write a dump/cache/report/tmp artifact (upstream writeLogFile)."""
    file_name = opts["fileName"]
    file_ext = opts["fileExt"]
    file_content = opts["fileContent"]
    file_type = opts.get("type") or "dump"
    target_dir = get_midscene_run_dir(file_type)

    if file_type != "dump":
        path = Path(target_dir) / f"{file_name}.{file_ext}"
        path.write_text(
            json.dumps(file_content, ensure_ascii=False), encoding="utf-8"
        )

    if opts.get("generateReport"):
        return write_dump_report(file_name, file_content, opts.get("appendReport"))

    return str(Path(target_dir) / f"{file_name}.{file_ext}")


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
    import asyncio

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
