"""HTML report helpers (upstream dump/html-utils.ts).

The Python SDK only writes self-contained HTML reports, so the Node streaming
scanner is reduced to: escape dump payloads, inject dump scripts into the
report template, and persist dump/log artifacts.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

from loguru import logger

from midscene.core.constants import IS_REPORT_BUILD
from midscene.core.report_html_template import _TEMPLATE
from midscene.shared.env import get_midscene_run_dir

_report_initialized: Dict[str, bool] = {}
_report_group_ids: Dict[str, str] = {}


def _uuid() -> str:
    return uuid.uuid4().hex


def escape_script_tag(value: str) -> str:
    """Escape angle brackets so inline JSON cannot break the host page."""
    return value.replace("<", "__midscene_lt__").replace(">", "__midscene_gt__")


def anti_escape_script_tag(value: str) -> str:
    """Reverse `escape_script_tag`."""
    return value.replace("__midscene_lt__", "<").replace("__midscene_gt__", ">")


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


__all__ = [
    "anti_escape_script_tag",
    "escape_script_tag",
    "get_report_tpl",
    "insert_content_before_closing_html",
    "insert_script_before_closing_html",
    "report_html_content",
    "write_dump_report",
    "write_log_file",
]
