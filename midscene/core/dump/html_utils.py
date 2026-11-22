"""HTML report helpers (upstream dump/html-utils.ts).

The Python SDK only writes self-contained HTML reports, so the Node streaming
scanner is reduced to: escape dump payloads, inject dump scripts into the
report template, and persist dump/log artifacts.
"""

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union
from urllib.parse import quote

from loguru import logger

from midscene.core.constants import IS_REPORT_BUILD
from midscene.core.dump.report_artifact_store import assert_report_artifact_path
from midscene.core.report_html_template import _TEMPLATE
from midscene.shared.env import get_midscene_run_dir

DATA_SCREENSHOT_MODE_ATTR = "data-screenshot-mode"
REPORT_ARTIFACT_SCRIPT_TYPE = "midscene_report_artifact"
TEST_RUN_REPORT_SCRIPT_TYPE = "midscene_test_run_dump"

STREAMING_CHUNK_SIZE = 64 * 1024

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


def _iter_tag_contents(
    file_path: str,
    open_tag: str,
    close_tag: str,
    chunk_size: int = STREAMING_CHUNK_SIZE,
) -> Iterator[str]:
    """Yield the contents between matching tags while keeping memory bounded."""
    with open(file_path, "r", encoding="utf-8") as handle:
        pending = ""
        capturing = False
        content = ""
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            data = pending + chunk
            pending = ""
            search = 0
            while True:
                if not capturing:
                    start = data.find(open_tag, search)
                    if start == -1:
                        keep = max(0, len(open_tag) - 1)
                        pending = data[-keep:] if keep else ""
                        break
                    search = start + len(open_tag)
                    capturing = True
                    content = ""
                    continue
                end = data.find(close_tag, search)
                if end == -1:
                    keep = max(0, len(close_tag) - 1)
                    if keep:
                        cut = max(search, len(data) - keep)
                        content += data[search:cut]
                        pending = data[cut:]
                    else:
                        content += data[search:]
                        pending = ""
                    break
                content += data[search:end]
                yield content
                capturing = False
                content = ""
                search = end + len(close_tag)


_SCRIPT_TYPE_PATTERN = re.compile(
    r"""(?:^|\s)type\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_IMAGE_ID_ATTRIBUTE_PATTERN = re.compile(
    r"""(?:^|\s)data-id\s*=\s*["']([a-z0-9_-]{1,128})["']""", re.IGNORECASE
)


def _script_type(attributes: str) -> Optional[str]:
    match = _SCRIPT_TYPE_PATTERN.search(attributes)
    return match.group(1) if match else None


def stream_dump_scripts_sync(
    file_path: str,
    visitor: Callable[[Dict[str, str]], bool],
) -> None:
    """Stream every ``midscene_web_dump`` script; return early when asked."""
    for content in _iter_tag_contents(file_path, "<script", "</script>"):
        tag_end = content.find(">")
        if tag_end == -1:
            continue
        if _script_type(content[:tag_end]) != "midscene_web_dump":
            continue
        open_tag = "<script" + content[: tag_end + 1]
        if visitor({"openTag": open_tag, "content": content[tag_end + 1 :]}):
            return


def extract_all_dump_scripts_sync(file_path: str) -> List[Dict[str, str]]:
    """Return every ``midscene_web_dump`` script tag with its open tag."""
    results: List[Dict[str, str]] = []
    stream_dump_scripts_sync(
        file_path,
        lambda dump: results.append(dump) or False,
    )
    return results


def extract_last_dump_script_sync(file_path: str) -> str:
    """Return the last embedded dump payload, or an empty string."""
    last = ""
    for content in _iter_tag_contents(file_path, "<script", "</script>"):
        tag_end = content.find(">")
        if tag_end == -1:
            continue
        if _script_type(content[:tag_end]) != "midscene_web_dump":
            continue
        last = content[tag_end + 1 :].strip()
    return last


def stream_inline_report_images(
    file_path: str,
    visit: Callable[[str, str], bool],
) -> None:
    """Visit one ``midscene-image`` payload at a time."""
    for content in _iter_tag_contents(file_path, "<script", "</script>"):
        tag_end = content.find(">")
        if tag_end == -1:
            continue
        attributes = content[:tag_end]
        if _script_type(attributes) != "midscene-image":
            continue
        id_match = _IMAGE_ID_ATTRIBUTE_PATTERN.search(attributes)
        if not id_match:
            continue
        if visit(
            id_match.group(1),
            anti_escape_script_tag(content[tag_end + 1 :]),
        ):
            return


def extract_report_artifact_path_sync(file_path: str) -> Optional[str]:
    """Extract the manifest path declared by a directory report."""
    for content in _iter_tag_contents(file_path, "<script", "</script>"):
        tag_end = content.find(">")
        if tag_end == -1:
            continue
        if _script_type(content[:tag_end]) != REPORT_ARTIFACT_SCRIPT_TYPE:
            continue
        value = json.loads(anti_escape_script_tag(content[tag_end + 1 :]))
        return assert_report_artifact_path(value)
    return None


def parse_image_scripts(html: str) -> Dict[str, str]:
    """Collect inline report images from an HTML string by id."""
    image_map: Dict[str, str] = {}
    pattern = re.compile(
        r'<script type="midscene-image" data-id="([^"]+)">([\s\S]*?)</script>'
    )
    for match in pattern.finditer(html):
        image_map[match.group(1)] = anti_escape_script_tag(match.group(2))
    return image_map


def _encode_attribute(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return quote(str(value), safe="-_.!~*'()")


def generate_dump_script_tag(
    json_string: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a ``midscene_web_dump`` tag with optional attributes."""
    attr_string = ""
    if attributes:
        attr_string = " " + " ".join(
            f'{key}="{_encode_attribute(value)}"'
            for key, value in attributes.items()
            if value is not None
        )
    return (
        '<script type="midscene_web_dump"'
        + attr_string
        + ">"
        + escape_script_tag(json_string)
        + "</script>"
    )


def generate_image_script_tag(image_id: str, data: str) -> str:
    """Build an inline ``midscene-image`` tag."""
    return (
        '<script type="midscene-image" data-id="'
        + image_id
        + '">'
        + escape_script_tag(data)
        + "</script>"
    )


def generate_report_artifact_script_tag(path: str) -> str:
    assert_report_artifact_path(path)
    return (
        '<script type="'
        + REPORT_ARTIFACT_SCRIPT_TYPE
        + '">'
        + json.dumps(path)
        + "</script>"
    )


def generate_test_run_report_script_tag(dump: Dict[str, Any]) -> str:
    return (
        '<script type="'
        + TEST_RUN_REPORT_SCRIPT_TYPE
        + '">\n'
        + escape_script_tag(json.dumps(dump, ensure_ascii=False))
        + "\n</script>\n"
    )


def get_base_url_fix_script() -> str:
    """Inline script that fixes relative URL resolution for directory reports."""
    return (
        "\n<script>(function(){"
        'var p=window.location.pathname;'
        'if(p.endsWith("/")||/\\.\\w+$/.test(p))return;'
        'var b=document.createElement("base");'
        'b.href=p+"/";'
        "document.head.insertBefore(b,document.head.firstChild)"
        "})()"
        "</script>"
        "\n"
    )


def _clean_html_comment_value(value: Any) -> str:
    text = "N/A" if value is None else str(value)
    return text.replace("\0", "").replace("--", "- -")


def _format_model_brief_for_agent(brief: Dict[str, Any]) -> str:
    intent = brief.get("intent") or "default"
    model = brief.get("name") or "unknown"
    description = (
        f" ({brief['modelDescription']})" if brief.get("modelDescription") else ""
    )
    return f"{intent}: {model}{description}"


def _has_usage_model_info(usage: Optional[Dict[str, Any]]) -> bool:
    if not usage:
        return False
    return any(
        usage.get(key)
        for key in (
            "model_name",
            "response_model_name",
            "model_description",
            "intent",
        )
    )


def _format_usage_model_for_agent(source: str, usage: Dict[str, Any]) -> str:
    intent = usage.get("intent") or source
    model = usage.get("model_name") or usage.get("response_model_name") or "unknown"
    description = (
        f" ({usage['model_description']})"
        if usage.get("model_description")
        else ""
    )
    return f"{intent}: {model}{description}"


def _collect_usage_models_for_agent(report: Dict[str, Any]) -> str:
    models: Dict[str, str] = {}
    executions = report.get("executions")
    if not isinstance(executions, list):
        executions = []
    for execution in executions:
        tasks = execution.get("tasks") if isinstance(execution, dict) else None
        if not isinstance(tasks, list):
            tasks = []
        for task in tasks:
            for source, usage in (
                ("main", task.get("usage")),
                ("searchArea", task.get("searchAreaUsage")),
            ):
                if not _has_usage_model_info(usage):
                    continue
                formatted = _format_usage_model_for_agent(source, usage)
                models[formatted] = formatted
    return "; ".join(models.values())


def generate_agent_report_comment(report: Dict[str, Any]) -> str:
    """Build the agent-readable HTML comment embedded in every report."""
    executions = report.get("executions")
    if not isinstance(executions, list):
        executions = []
    task_count = sum(
        len(execution.get("tasks") or [])
        for execution in executions
        if isinstance(execution, dict)
    )
    model_briefs = report.get("modelBriefs")
    if isinstance(model_briefs, list) and model_briefs:
        models = "; ".join(
            _format_model_brief_for_agent(brief) for brief in model_briefs
        )
    else:
        models = _collect_usage_models_for_agent(report) or "No model metadata recorded"

    lines = [
        "For Agent Analysis:",
        f"Report: {_clean_html_comment_value(report.get('groupName'))}",
        f"SDK: {_clean_html_comment_value(report.get('sdkVersion'))}",
        f"Device: {_clean_html_comment_value(report.get('deviceType'))}",
        f"Executions: {len(executions)}; Tasks: {task_count}",
        f"Models: {_clean_html_comment_value(models)}",
        'Structured report JSON is stored in script[type="midscene_web_dump"] tags near this comment.',
        'Screenshots are stored as script[type="midscene-image"] tags or files referenced by screenshot refs.',
        "For AI analysis, inspect each execution task for type, status, timing, param, output, usage, searchAreaUsage, recorder, and screenshot refs.",
        "Use the Markdown export when available; it contains the same report context plus image links for agent review.",
    ]
    return "\n<!--\n" + "\n".join(lines) + "\n-->\n"


__all__ = [
    "DATA_SCREENSHOT_MODE_ATTR",
    "REPORT_ARTIFACT_SCRIPT_TYPE",
    "STREAMING_CHUNK_SIZE",
    "TEST_RUN_REPORT_SCRIPT_TYPE",
    "anti_escape_script_tag",
    "escape_script_tag",
    "extract_all_dump_scripts_sync",
    "extract_last_dump_script_sync",
    "extract_report_artifact_path_sync",
    "generate_agent_report_comment",
    "generate_dump_script_tag",
    "generate_image_script_tag",
    "generate_report_artifact_script_tag",
    "generate_test_run_report_script_tag",
    "get_base_url_fix_script",
    "get_report_tpl",
    "insert_content_before_closing_html",
    "insert_script_before_closing_html",
    "parse_image_scripts",
    "report_html_content",
    "stream_dump_scripts_sync",
    "stream_inline_report_images",
    "write_dump_report",
    "write_log_file",
]
