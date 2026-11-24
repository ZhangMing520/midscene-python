"""HTML report helpers (upstream dump/html-utils.ts).

Escapes dump payloads, injects dump scripts into the report template, persists
dump/log artifacts, and streams script tags out of large report files without
loading the whole document into memory.
"""

import asyncio
import codecs
import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from loguru import logger

from midscene.core.constants import IS_REPORT_BUILD
from midscene.core.dump.report_artifact_store import assert_report_artifact_path
from midscene.core.report_html_template import _TEMPLATE
from midscene.shared.env import get_midscene_run_dir

DATA_SCREENSHOT_MODE_ATTR = "data-screenshot-mode"
REPORT_ARTIFACT_SCRIPT_TYPE = "midscene_report_artifact"
TEST_RUN_REPORT_SCRIPT_TYPE = "midscene_test_run_dump"

STREAMING_CHUNK_SIZE = 64 * 1024

_report_initialized: dict[str, bool] = {}
_report_group_ids: dict[str, str] = {}


def _uuid() -> str:
    return uuid.uuid4().hex


def escape_script_tag(value: str) -> str:
    """Escape angle brackets so inline JSON cannot break the host page."""
    return value.replace("<", "__midscene_lt__").replace(">", "__midscene_gt__")


def anti_escape_script_tag(value: str) -> str:
    """Reverse `escape_script_tag`."""
    return value.replace("__midscene_lt__", "<").replace("__midscene_gt__", ">")


# Upstream aliases (html-utils.ts): escapeContent / unescapeContent.
escape_content = escape_script_tag
unescape_content = anti_escape_script_tag


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


def _report_script_tag(dump_data: str | dict[str, Any], group_id: str) -> str:
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
    dump_data: str | dict[str, Any],
    report_path: str | None = None,
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
    dump_data: str | dict[str, Any],
    append_report: bool = False,
) -> str | None:
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


def write_log_file(opts: dict[str, Any]) -> str | None:
    """Write a dump/cache/report/tmp artifact (upstream writeLogFile)."""
    file_name = opts["fileName"]
    file_ext = opts["fileExt"]
    file_content = opts["fileContent"]
    file_type = opts.get("type") or "dump"
    target_dir = get_midscene_run_dir(file_type)

    if file_type != "dump":
        path = Path(target_dir) / f"{file_name}.{file_ext}"
        path.write_text(json.dumps(file_content, ensure_ascii=False), encoding="utf-8")

    if opts.get("generateReport"):
        return write_dump_report(file_name, file_content, opts.get("appendReport"))

    return str(Path(target_dir) / f"{file_name}.{file_ext}")


TagMatchCallback = Callable[[str], bool]


class _StreamingTagMatcher:
    """Incremental matcher for open/close tagged chunks (upstream StreamingTagMatcher)."""

    def __init__(
        self,
        open_tag: str,
        close_tag: str,
        on_match: TagMatchCallback,
    ) -> None:
        self._open_tag = open_tag
        self._close_tag = close_tag
        self._on_match = on_match
        self._leftover = ""
        self._capturing = False
        self._current_content = ""

    def push(self, next_chunk: str) -> bool:
        chunk = self._leftover + next_chunk
        self._leftover = ""
        search_start = 0

        while search_start < len(chunk):
            if not self._capturing:
                start_index = chunk.find(self._open_tag, search_start)
                if start_index == -1:
                    retained = max(0, len(self._open_tag) - 1)
                    self._leftover = chunk[-retained:] if retained else ""
                    return False
                self._capturing = True
                search_start = start_index + len(self._open_tag)

            end_index = chunk.find(self._close_tag, search_start)
            if end_index != -1:
                self._current_content += chunk[search_start:end_index]
                if self._on_match(self._current_content):
                    return True
                self._capturing = False
                self._current_content = ""
                search_start = end_index + len(self._close_tag)
                continue

            retained = max(0, len(self._close_tag) - 1)
            content_end = max(search_start, len(chunk) - retained)
            self._current_content += chunk[search_start:content_end]
            self._leftover = chunk[content_end:]
            return False

        return False


def _iter_tag_contents(
    file_path: str,
    open_tag: str,
    close_tag: str,
    chunk_size: int = STREAMING_CHUNK_SIZE,
) -> Iterator[str]:
    """Yield the contents between matching tags while keeping memory bounded."""
    matches: list[str] = []
    matcher = _StreamingTagMatcher(
        open_tag,
        close_tag,
        lambda content: matches.append(content) or False,
    )
    decoder = codecs.getincrementaldecoder("utf-8")()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            matcher.push(decoder.decode(chunk))
            while matches:
                yield matches.pop(0)
    matcher.push(decoder.decode(b"", final=True))
    while matches:
        yield matches.pop(0)


def stream_scan_tags(
    file_path: str,
    open_tag: str,
    close_tag: str,
    on_match: TagMatchCallback,
) -> None:
    """Stream through a file and invoke ``on_match`` for each complete tag.

    Memory usage: O(chunk_size + tag_size), not O(file_size).
    """
    matcher = _StreamingTagMatcher(open_tag, close_tag, on_match)
    decoder = codecs.getincrementaldecoder("utf-8")()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(STREAMING_CHUNK_SIZE)
            if not chunk:
                break
            if matcher.push(decoder.decode(chunk)):
                return
    matcher.push(decoder.decode(b"", final=True))


async def stream_scan_tags_async(
    file_path: str,
    open_tag: str,
    close_tag: str,
    on_match: TagMatchCallback,
) -> None:
    """Asynchronously stream tags without blocking the event loop."""
    await asyncio.to_thread(stream_scan_tags, file_path, open_tag, close_tag, on_match)


_SCRIPT_TYPE_PATTERN = re.compile(
    r"""(?:^|\s)type\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_IMAGE_ID_ATTRIBUTE_PATTERN = re.compile(
    r"""(?:^|\s)data-id\s*=\s*["']([a-z0-9_-]{1,128})["']""", re.IGNORECASE
)


def _script_type(attributes: str) -> str | None:
    match = _SCRIPT_TYPE_PATTERN.search(attributes)
    return match.group(1) if match else None


def stream_dump_scripts_sync(
    file_path: str,
    visitor: Callable[[dict[str, str]], bool],
) -> None:
    """Stream every ``midscene_web_dump`` script; return early when asked."""

    def visit(content: str) -> bool:
        tag_end = content.find(">")
        if tag_end == -1:
            return False
        if _script_type(content[:tag_end]) != "midscene_web_dump":
            return False
        open_tag = "<script" + content[: tag_end + 1]
        return visitor({"openTag": open_tag, "content": content[tag_end + 1 :]})

    stream_scan_tags(file_path, "<script", "</script>", visit)


async def stream_dump_scripts_async(
    file_path: str,
    visitor: Callable[[dict[str, str]], bool],
) -> None:
    """Consume complete elements so dump-tag strings in the Viewer are never payloads."""

    def visit(content: str) -> bool:
        tag_end = content.find(">")
        if tag_end == -1:
            return False
        if _script_type(content[:tag_end]) != "midscene_web_dump":
            return False
        open_tag = "<script" + content[: tag_end + 1]
        return visitor({"openTag": open_tag, "content": content[tag_end + 1 :]})

    await stream_scan_tags_async(file_path, "<script", "</script>", visit)


def extract_all_dump_scripts_sync(file_path: str) -> list[dict[str, str]]:
    """Return every ``midscene_web_dump`` script tag with its open tag."""
    results: list[dict[str, str]] = []
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


def _report_artifact_path_extractor(
    file_path: str,
) -> dict[str, Any]:
    """Build the visitor/state pair used by the sync and async extractors."""
    state: dict[str, Any] = {"path": None}

    def visit(content: str) -> bool:
        tag_end = content.find(">")
        if tag_end == -1:
            return False
        if _script_type(content[:tag_end]) != REPORT_ARTIFACT_SCRIPT_TYPE:
            return False
        if state["path"] is not None:
            raise ValueError(f"Report contains multiple artifact entries: {file_path}")
        value = json.loads(anti_escape_script_tag(content[tag_end + 1 :]))
        state["path"] = assert_report_artifact_path(value)
        return False

    return {"state": state, "visit": visit}


def extract_report_artifact_path_sync(file_path: str) -> str | None:
    """Extract the manifest path declared by a directory report."""
    extractor = _report_artifact_path_extractor(file_path)
    stream_scan_tags(file_path, "<script", "</script>", extractor["visit"])
    return extractor["state"]["path"]


async def extract_report_artifact_path_async(
    file_path: str,
) -> str | None:
    """Asynchronously extract the manifest path declared by a directory report."""
    extractor = _report_artifact_path_extractor(file_path)
    await stream_scan_tags_async(file_path, "<script", "</script>", extractor["visit"])
    return extractor["state"]["path"]


def extract_test_run_report_dump_sync(
    file_path: str,
) -> dict[str, Any] | None:
    """Extract the single Midscene Test report dump from an HTML file."""
    state: dict[str, Any] = {"result": None}

    def visit(content: str) -> bool:
        tag_end = content.find(">")
        if tag_end == -1:
            return False
        if _script_type(content[:tag_end]) != TEST_RUN_REPORT_SCRIPT_TYPE:
            return False
        if state["result"] is not None:
            raise ValueError(
                f"Report contains multiple Midscene Test dumps: {file_path}"
            )
        parsed = json.loads(anti_escape_script_tag(content[tag_end + 1 :]))
        if (
            not isinstance(parsed, dict)
            or parsed.get("schemaVersion") != 1
            or parsed.get("kind") != "test-runner"
            or not isinstance(parsed.get("projects"), list)
        ):
            raise ValueError(f"Invalid Midscene Test report dump: {file_path}")
        state["result"] = parsed
        return False

    # Consume executable scripts as whole elements: the embedded viewer itself
    # contains report-writer source with data-tag strings that are not payloads.
    stream_scan_tags(file_path, "<script", "</script>", visit)
    return state["result"]


def parse_image_scripts(html: str) -> dict[str, str]:
    """Collect inline report images from an HTML string by id."""
    image_map: dict[str, str] = {}
    pattern = re.compile(
        r'<script type="midscene-image" data-id="([^"]+)">([\s\S]*?)</script>'
    )
    for match in pattern.finditer(html):
        image_map[match.group(1)] = anti_escape_script_tag(match.group(2))
    return image_map


def parse_dump_script(html: str) -> str:
    """Return the LAST dump payload embedded in an HTML string."""
    script_open_tag = '<script type="midscene_web_dump"'
    close_tag = "</script>"

    last_open_index = html.rfind(script_open_tag)
    if last_open_index == -1:
        raise ValueError("No dump script found in HTML")

    tag_end_index = html.find(">", last_open_index)
    if tag_end_index == -1:
        raise ValueError("No dump script found in HTML")

    close_index = html.find(close_tag, tag_end_index)
    if close_index == -1:
        raise ValueError("No dump script found in HTML")

    return unescape_content(html[tag_end_index + 1 : close_index])


def parse_dump_script_attributes(html: str) -> dict[str, str]:
    """Decode the attributes of the first ``midscene_web_dump`` script tag."""
    match = re.search(r'<script type="midscene_web_dump"([^>]*)>', html)
    if not match:
        return {}

    attributes: dict[str, str] = {}
    for attribute in re.finditer(r'(\w+)="([^"]*)"', match.group(1)):
        key, value = attribute.group(1), attribute.group(2)
        if key != "type":
            attributes[key] = unquote(value)
    return attributes


_IMAGE_SCRIPT_ID_PATTERN = re.compile(
    r'^ data-id="([a-z0-9_-]{1,128})">', re.IGNORECASE
)


def _parse_image_script_id(content_after_type: str) -> str | None:
    match = _IMAGE_SCRIPT_ID_PATTERN.match(content_after_type)
    return match.group(1) if match else None


def stream_image_scripts_to_file(
    src_file_path: str,
    dest_file_path: str,
    written_image_ids: set[str] | None = None,
) -> None:
    """Stream image script tags from source file directly to output file.

    Memory usage: O(single_image_size), not O(all_images_size).
    """
    open_tag = '<script type="midscene-image"'
    close_tag = "</script>"
    written = written_image_ids if written_image_ids is not None else set()

    def visit(content: str) -> bool:
        image_id = _parse_image_script_id(content)
        if not image_id or image_id in written:
            return False
        with open(dest_file_path, "a", encoding="utf-8") as handle:
            handle.write(f"{open_tag}{content}{close_tag}\n")
        written.add(image_id)
        return False

    stream_scan_tags(src_file_path, open_tag, close_tag, visit)


async def collect_image_script_ids(file_path: str) -> set[str]:
    """Collect IDs of real inline image script tags without loading the report."""
    image_ids: set[str] = set()

    def visit(content: str) -> bool:
        image_id = _parse_image_script_id(content)
        if image_id:
            image_ids.add(image_id)
        return False

    await stream_scan_tags_async(
        file_path, '<script type="midscene-image"', "</script>", visit
    )
    return image_ids


def _encode_attribute(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return quote(str(value), safe="-_.!~*'()")


def generate_dump_script_tag(
    json_string: str,
    attributes: dict[str, Any] | None = None,
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


def generate_test_run_report_script_tag(dump: dict[str, Any]) -> str:
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
        "var p=window.location.pathname;"
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


def _format_model_brief_for_agent(brief: dict[str, Any]) -> str:
    intent = brief.get("intent") or "default"
    model = brief.get("name") or "unknown"
    description = (
        f" ({brief['modelDescription']})" if brief.get("modelDescription") else ""
    )
    return f"{intent}: {model}{description}"


def _has_usage_model_info(usage: dict[str, Any] | None) -> bool:
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


def _format_usage_model_for_agent(source: str, usage: dict[str, Any]) -> str:
    intent = usage.get("intent") or source
    model = usage.get("model_name") or usage.get("response_model_name") or "unknown"
    description = (
        f" ({usage['model_description']})" if usage.get("model_description") else ""
    )
    return f"{intent}: {model}{description}"


def _collect_usage_models_for_agent(report: dict[str, Any]) -> str:
    models: dict[str, str] = {}
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


def generate_agent_report_comment(report: dict[str, Any]) -> str:
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


def extract_image_by_id_sync(html_path: str, image_id: str) -> str | None:
    """Re-export of ``screenshot_store.extract_image_by_id_sync``."""
    from midscene.core.dump.screenshot_store import (
        extract_image_by_id_sync as _extract_image_by_id_sync,
    )

    return _extract_image_by_id_sync(html_path, image_id)


__all__ = [
    "DATA_SCREENSHOT_MODE_ATTR",
    "extract_image_by_id_sync",
    "REPORT_ARTIFACT_SCRIPT_TYPE",
    "STREAMING_CHUNK_SIZE",
    "TEST_RUN_REPORT_SCRIPT_TYPE",
    "anti_escape_script_tag",
    "collect_image_script_ids",
    "escape_content",
    "escape_script_tag",
    "extract_all_dump_scripts_sync",
    "extract_last_dump_script_sync",
    "extract_report_artifact_path_async",
    "extract_report_artifact_path_sync",
    "extract_test_run_report_dump_sync",
    "generate_agent_report_comment",
    "generate_dump_script_tag",
    "generate_image_script_tag",
    "generate_report_artifact_script_tag",
    "generate_test_run_report_script_tag",
    "get_base_url_fix_script",
    "get_report_tpl",
    "insert_content_before_closing_html",
    "insert_script_before_closing_html",
    "parse_dump_script",
    "parse_dump_script_attributes",
    "parse_image_scripts",
    "report_html_content",
    "stream_dump_scripts_async",
    "stream_dump_scripts_sync",
    "stream_image_scripts_to_file",
    "stream_inline_report_images",
    "stream_scan_tags",
    "stream_scan_tags_async",
    "unescape_content",
    "write_dump_report",
    "write_log_file",
]
