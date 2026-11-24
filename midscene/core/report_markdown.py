"""Markdown report rendering (upstream core/src/report-markdown.ts)."""

import datetime
import json
import math
import re
from pathlib import Path
from typing import Any

from midscene.core.dump.image_reference import image_ref_file_extension
from midscene.core.dump.screenshot_restoration import _externalize_images
from midscene.core.dump.screenshot_store import normalize_screenshot_ref
from midscene.core.report_cli import (
    _DUMP_HEADER_KEYS,
    collect_report_executions,
)
from midscene.core.report_stats import collect_report_summary
from midscene.core.screenshot_item import ScreenshotItem

_SCREENSHOT_DATA_URL_PATTERN = re.compile(
    r"^data:image/(png|jpeg|jpg);base64,([\s\S]*)$", re.IGNORECASE
)
_RAW_BASE64_BODY_PATTERN = re.compile(r"^[a-zA-Z0-9+/=\s]+$")
_JSON_CONTEXT_MAX_STRING_LENGTH = 12_000
_UNDEFINED = object()

_UsageKeys = (
    "intent",
    "model_name",
    "model_description",
    "prompt_tokens",
    "cached_input",
    "completion_tokens",
    "total_tokens",
    "time_cost",
    "request_id",
)


def _to_execution_dump(execution: Any) -> dict[str, Any]:
    if not isinstance(execution, dict):
        raise ValueError("executionToMarkdown: execution is required")
    if not isinstance(execution.get("tasks"), list):
        raise ValueError("executionToMarkdown: execution.tasks must be an array")
    if not execution.get("name"):
        raise ValueError("executionToMarkdown: execution.name is required")
    return execution


def _to_report_dump(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("reportToMarkdown: report is required")
    if not isinstance(report.get("executions"), list):
        raise ValueError("reportToMarkdown: report.executions must be an array")
    return report


def _format_time(timestamp: Any) -> str:
    if (
        not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or math.isnan(timestamp)
    ):
        return "N/A"
    milliseconds = int(timestamp)
    moment = datetime.datetime.fromtimestamp(milliseconds / 1000, tz=datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{milliseconds % 1000:03d}Z"


def _stringify_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return repr(value)


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _stringify_number(value) if math.isfinite(value) else "N/A"
    return str(value)


def _escape_table_cell(value: Any) -> str:
    return _format_value(value).replace("|", "\\|").replace("\n", "<br>")


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    return [
        "| " + " | ".join(_escape_table_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *[
            "| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |"
            for row in rows
        ],
    ]


def _model_brief_rows(model_briefs: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            brief.get("intent") or "default",
            brief.get("name") or "N/A",
            brief.get("modelDescription") or "N/A",
        ]
        for brief in model_briefs
    ]


def _has_usage(usage: dict[str, Any] | None) -> bool:
    if not isinstance(usage, dict):
        return False
    return any(usage.get(key) is not None for key in _UsageKeys)


def _model_rows_from_usage(report: dict[str, Any]) -> list[list[Any]]:
    rows: dict[str, list[Any]] = {}

    def add_usage(source: str, usage: Any) -> None:
        if not _has_usage(usage):
            return
        intent = usage.get("intent") or source
        model = usage.get("model_name") or usage.get("response_model_name")
        description = usage.get("model_description")
        key = f"{intent}\0{model or ''}\0{description or ''}"
        if key in rows:
            return
        rows[key] = [intent, model or "N/A", description or "N/A"]

    for execution in report.get("executions") or []:
        for task in execution.get("tasks") or []:
            add_usage("main", task.get("usage"))
            add_usage(
                "searchArea",
                task.get("searchAreaUsage") or task.get("search_area_usage"),
            )
    return list(rows.values())


def _usage_value(usage: dict[str, Any] | None, key: str) -> float:
    value = usage.get(key) if isinstance(usage, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value):
            return value
    return 0


def _usage_total_tokens(usage: dict[str, Any]) -> float:
    explicit = _usage_value(usage, "total_tokens")
    if explicit > 0:
        return explicit
    return _usage_value(usage, "prompt_tokens") + _usage_value(
        usage, "completion_tokens"
    )


def _usage_rows_for_task(task: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []

    def append_usage(source: str, usage: Any) -> None:
        if not _has_usage(usage):
            return
        rows.append(
            [
                source,
                usage.get("intent"),
                usage.get("model_name") or usage.get("response_model_name"),
                usage.get("model_description"),
                _usage_value(usage, "prompt_tokens"),
                _usage_value(usage, "cached_input"),
                _usage_value(usage, "completion_tokens"),
                _usage_total_tokens(usage),
                _usage_value(usage, "time_cost"),
                usage.get("request_id"),
            ]
        )

    append_usage("main", task.get("usage"))
    append_usage(
        "searchArea", task.get("searchAreaUsage") or task.get("search_area_usage")
    )
    return rows


def _sanitize_json_for_markdown(value: Any, seen: set | None = None) -> Any:
    if seen is None:
        seen = set()
    if isinstance(value, str):
        if (
            _SCREENSHOT_DATA_URL_PATTERN.match(value)
            or len(value) > 1_000_000
            or re.match(r"^[a-zA-Z0-9+/=\s]{100000,}$", value)
        ):
            return f"[omitted image/base64 string, length={len(value)}]"
        if len(value) > _JSON_CONTEXT_MAX_STRING_LENGTH:
            return (
                f"{value[:_JSON_CONTEXT_MAX_STRING_LENGTH]}\n"
                f"[truncated, original length={len(value)}]"
            )
        return value

    if value is None or isinstance(value, (int, float, bool)):
        return value

    if not isinstance(value, (dict, list)):
        return _UNDEFINED

    if id(value) in seen:
        return "[omitted circular reference]"
    seen.add(id(value))

    if isinstance(value, list):
        sanitized_list = [_sanitize_json_for_markdown(item, seen) for item in value]
        seen.discard(id(value))
        return sanitized_list
    else:
        sanitized_dict: dict[str, Any] = {}
        for key, entry in value.items():
            if isinstance(entry, str) and re.search(
                r"(^|_|-)(base64|screenshotBase64|imageBase64)$",
                key,
                re.IGNORECASE,
            ):
                sanitized_dict[key] = f"[omitted base64 string, length={len(entry)}]"
                continue
            sanitized_dict[key] = _sanitize_json_for_markdown(entry, seen)
    seen.discard(id(value))
    return sanitized_dict


def _append_json_section(lines: list[str], title: str, value: Any) -> None:
    if value is None or value == "":
        return
    sanitized = _sanitize_json_for_markdown(value)
    if sanitized is _UNDEFINED:
        return
    lines.extend(
        [
            "",
            f"### {title}",
            "",
            "```json",
            json.dumps(sanitized, ensure_ascii=False, indent=2),
            "```",
        ]
    )


def _append_text_section(lines: list[str], title: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    lines.extend(
        [
            "",
            f"### {title}",
            "",
            "```text",
            value.replace("```", "` ` `"),
            "```",
        ]
    )


def _resolve_task_timing(task: dict[str, Any]) -> dict[str, Any]:
    timing = task.get("timing")
    if not isinstance(timing, dict):
        return {}
    start = timing.get("start")
    if start is None:
        start = timing.get("callAiStart")
    if start is None:
        start = timing.get("callActionStart")
    end = timing.get("end")
    if end is None:
        end = timing.get("callAiEnd")
    if end is None:
        end = timing.get("callActionEnd")
    if end is None:
        end = timing.get("captureAfterCallingSnapshotEnd")
    cost = timing.get("cost")
    if (
        cost is None
        and isinstance(start, (int, float))
        and isinstance(end, (int, float))
    ):
        cost = end - start
    return {"start": start, "end": end, "cost": cost}


def _locate_param_str(locate: Any) -> str:
    if not locate:
        return ""
    if isinstance(locate, str):
        return locate
    if isinstance(locate, dict):
        prompt_display = locate.get("promptDisplay")
        if isinstance(prompt_display, str):
            return prompt_display
        prompt = locate.get("prompt")
        if isinstance(prompt, dict) and prompt.get("prompt"):
            return str(prompt["prompt"])
        if isinstance(prompt, str):
            return prompt
        description = locate.get("description")
        if isinstance(description, str):
            return description
    return ""


def _scroll_param_str(scroll_param: dict[str, Any] | None) -> str:
    if not scroll_param:
        return ""
    return (
        f"{scroll_param.get('direction') or 'down'}, "
        f"{scroll_param.get('scrollType') or 'singleAction'}, "
        f"{scroll_param.get('distance') or 'distance-not-set'}"
    )


def _pull_param_str(pull_param: dict[str, Any] | None) -> str:
    if not pull_param:
        return ""
    parts = [f"direction: {pull_param.get('direction') or 'down'}"]
    if pull_param.get("distance"):
        parts.append(f"distance: {pull_param['distance']}")
    if pull_param.get("duration"):
        parts.append(f"duration: {pull_param['duration']}ms")
    return ", ".join(parts)


def _to_content(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _extract_insight_param(task_param: Any) -> dict[str, Any]:
    if not task_param:
        return {"content": ""}

    def extract_images(source: dict[str, Any]) -> Any:
        multimodal = source.get("multimodalPrompt") or {}
        images = multimodal.get("images") if isinstance(multimodal, dict) else None
        return images if isinstance(images, list) else None

    if task_param.get("demand"):
        return {
            "content": _to_content(task_param["demand"]),
            "images": extract_images(task_param),
        }
    if task_param.get("assertion"):
        return {
            "content": _to_content(task_param["assertion"]),
            "images": extract_images(task_param),
        }
    if task_param.get("dataDemand") is not None:
        data_demand = task_param["dataDemand"]
        if isinstance(data_demand, str):
            return {"content": data_demand}
        if isinstance(data_demand, dict):
            return {
                "content": _to_content(data_demand.get("demand") or data_demand),
                "images": extract_images(data_demand),
            }
    return {"content": ""}


def _user_prompt_to_string(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        return "\n".join(
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            for item in prompt
        )
    if isinstance(prompt, dict):
        prompt_text = prompt.get("prompt")
        if isinstance(prompt_text, str):
            return prompt_text
        return json.dumps(prompt, ensure_ascii=False)
    return str(prompt)


def _format_param_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "None"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _param_str(task: dict[str, Any]) -> str:
    value: Any = _UNDEFINED
    task_type = task.get("type")
    sub_type = task.get("subType")
    param = task.get("param")
    if task_type == "Planning":
        if sub_type == "Locate":
            value = _locate_param_str(param)
        else:
            output = task.get("output") or {}
            if output.get("log"):
                value = output["log"]
            elif isinstance(param, dict) and param.get("userInstructionDisplay"):
                value = param["userInstructionDisplay"]
            elif isinstance(param, dict) and param.get("userInstruction"):
                value = _user_prompt_to_string(param["userInstruction"])
    if task_type == "Insight":
        value = _extract_insight_param(param).get("content")
    if task_type == "Action Space":
        locate = param.get("locate") if isinstance(param, dict) else None
        locate_str = _locate_param_str(locate) if locate else ""
        value = task.get("thought") or ""
        if isinstance(param, dict) and isinstance(param.get("timeMs"), (int, float)):
            value = f"{param['timeMs']}ms"
        elif isinstance(param, dict) and isinstance(param.get("scrollType"), str):
            value = _scroll_param_str(param)
        elif (
            isinstance(param, dict)
            and isinstance(param.get("direction"), str)
            and sub_type == "PullGesture"
        ):
            value = _pull_param_str(param)
        elif isinstance(param, dict) and "value" in param:
            value = param.get("value")
        elif isinstance(param, dict) and param:
            value = param
        if locate_str:
            if value and not isinstance(value, dict):
                value = f"{locate_str} - {_format_param_value(value)}"
            else:
                value = locate_str
    if value is _UNDEFINED:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        locate_str = _locate_param_str(value)
        if locate_str:
            return locate_str
        entries = list(value.items())
        if not entries:
            return ""
        if len(entries) == 1:
            key, item = entries[0]
            return f"{key}: {_format_param_value(item)}"
        return ", ".join(f"{key}: {_format_param_value(item)}" for key, item in entries)
    return _format_param_value(value)


def _type_str(task: dict[str, Any]) -> str:
    return task.get("subType") or task.get("type") or ""


def _safe_task_param(task: dict[str, Any]) -> str:
    readable = _param_str(task)
    if readable:
        return readable
    if task.get("type") == "Insight":
        return _extract_insight_param(task.get("param")).get("content") or ""
    return ""


def _format_size(size: Any) -> str | None:
    if not isinstance(size, dict):
        return None
    width = size.get("width")
    height = size.get("height")
    if (
        not isinstance(width, (int, float))
        or isinstance(width, bool)
        or not isinstance(height, (int, float))
        or isinstance(height, bool)
        or math.isnan(width)
        or math.isnan(height)
    ):
        return None
    return f"{_stringify_number(width)} x {_stringify_number(height)}"


def _extract_locate_center(task: dict[str, Any]) -> tuple[Any, Any] | None:
    output = task.get("output") or {}
    element = output.get("element") if isinstance(output, dict) else None
    candidates = []
    if isinstance(element, dict):
        candidates.append(element.get("center"))
    param = task.get("param") or {}
    if isinstance(param, dict):
        locate = param.get("locate")
        if isinstance(locate, dict):
            candidates.append(locate.get("center"))
        candidates.append(param.get("center"))
    for center in candidates:
        if (
            isinstance(center, list)
            and len(center) >= 2
            and isinstance(center[0], (int, float))
            and not isinstance(center[0], bool)
            and isinstance(center[1], (int, float))
            and not isinstance(center[1], bool)
        ):
            return (center[0], center[1])
    return None


def _try_extract_base64(screenshot: Any) -> str | None:
    if ScreenshotItem.is_screenshot_item(screenshot):
        try:
            value = screenshot.base64
        except Exception:  # noqa: BLE001 - released screenshots are optional
            return None
        return value or None
    if isinstance(screenshot, str):
        trimmed = screenshot.strip()
        match = _SCREENSHOT_DATA_URL_PATTERN.match(trimmed)
        if match:
            image_format = "jpeg" if match.group(1).lower() == "jpg" else "png"
            body = re.sub(r"\s", "", match.group(2))
            if not body:
                return None
            return f"data:image/{image_format};base64,{body}"
        if trimmed.startswith("data:") or not _RAW_BASE64_BODY_PATTERN.match(trimmed):
            return None
        body = re.sub(r"\s", "", trimmed)
        return f"data:image/png;base64,{body}" if body else None
    if isinstance(screenshot, dict):
        value = screenshot.get("base64")
        if isinstance(value, str) and value:
            return value
    return None


def _restored_source_ref(screenshot: Any) -> dict[str, Any] | None:
    if not isinstance(screenshot, dict):
        return None
    return normalize_screenshot_ref(screenshot.get("sourceRef"))


def _screenshot_attachment(
    screenshot: Any,
    screenshot_base_dir: str,
    execution_index: int,
    task_index: int,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    markdown_label = options.get("label") or f"task-{task_index + 1}"

    def result(attachment: dict[str, Any]) -> dict[str, Any]:
        resolver = options.get("resolveScreenshotFileName")
        if resolver is not None:
            attachment["suggestedFileName"] = resolver(attachment)
        return {
            "markdown": (
                f"\n![{markdown_label}]({screenshot_base_dir}/"
                f"{attachment['suggestedFileName']})"
            ),
            "attachment": attachment,
        }

    if ScreenshotItem.is_screenshot_item(screenshot):
        extension = screenshot.extension
        return result(
            {
                "id": screenshot.id,
                "suggestedFileName": (
                    f"execution-{execution_index + 1}-task-{task_index + 1}-"
                    f"{screenshot.id}.{extension}"
                ),
                "mimeType": "image/jpeg" if extension == "jpeg" else "image/png",
                "executionIndex": execution_index,
                "taskIndex": task_index,
                "base64Data": _try_extract_base64(screenshot),
            }
        )

    ref = normalize_screenshot_ref(screenshot)
    if ref is not None:
        extension = image_ref_file_extension(ref)
        return result(
            {
                "id": ref["id"],
                "suggestedFileName": (
                    f"execution-{execution_index + 1}-task-{task_index + 1}-"
                    f"{ref['id']}.{extension}"
                ),
                "sourceRef": ref,
                "mimeType": ref.get("mimeType"),
                "executionIndex": execution_index,
                "taskIndex": task_index,
                "base64Data": _try_extract_base64(screenshot),
            }
        )

    source_ref = _restored_source_ref(screenshot)
    if source_ref is not None:
        extension = image_ref_file_extension(source_ref)
        return result(
            {
                "id": source_ref["id"],
                "suggestedFileName": (
                    f"execution-{execution_index + 1}-task-{task_index + 1}-"
                    f"{source_ref['id']}.{extension}"
                ),
                "sourceRef": source_ref,
                "mimeType": source_ref.get("mimeType"),
                "executionIndex": execution_index,
                "taskIndex": task_index,
                "base64Data": _try_extract_base64(screenshot),
            }
        )

    base64 = _try_extract_base64(screenshot)
    if base64:
        extension = "jpeg" if base64.startswith("data:image/jpeg") else "png"
        suffix = (
            f"-{options['fallbackIdSuffix']}" if options.get("fallbackIdSuffix") else ""
        )
        image_id = f"restored-{execution_index + 1}-{task_index + 1}{suffix}"
        return result(
            {
                "id": image_id,
                "suggestedFileName": (
                    f"execution-{execution_index + 1}-task-{task_index + 1}-"
                    f"{image_id}.{extension}"
                ),
                "mimeType": f"image/{extension}",
                "executionIndex": execution_index,
                "taskIndex": task_index,
                "base64Data": base64,
            }
        )

    raise ValueError(
        "executionToMarkdown: missing screenshot for execution "
        f"#{execution_index + 1} task #{task_index + 1}"
    )


def _image_label_suffix(value: str) -> str:
    label = re.sub(r"[^a-z0-9._-]+", "-", str(value).lower())
    label = re.sub(r"-+", "-", label).strip("-")
    return label or "screenshot"


def _screenshots_markdown_section(
    task: dict[str, Any],
    screenshot_base_dir: str,
    execution_index: int,
    task_index: int,
    resolve_screenshot_file_name: Any | None = None,
) -> dict[str, Any]:
    lines: list[str] = ["", "### Screenshots"]
    attachments: list[dict[str, Any]] = []
    screenshot_index = 0

    ui_context = task.get("uiContext") or {}
    if isinstance(ui_context, dict) and ui_context.get("screenshot"):
        image_result = _screenshot_attachment(
            ui_context["screenshot"],
            screenshot_base_dir,
            execution_index,
            task_index,
            {
                "fallbackIdSuffix": "ui-context",
                "label": f"task-{task_index + 1}-ui-context",
                "resolveScreenshotFileName": resolve_screenshot_file_name,
            },
        )
        timing = _resolve_task_timing(task)
        screenshot_index += 1
        lines.append(
            f"- #{screenshot_index} type=ui-context, "
            f"ts={_format_time(timing.get('start'))}, timing=ui-context, "
            f"id={image_result['attachment']['id']}"
        )
        lines.append(image_result["markdown"])
        attachments.append(image_result["attachment"])

    for recorder_index, item in enumerate(task.get("recorder") or []):
        if not isinstance(item, dict) or not item.get("screenshot"):
            continue
        description_text = (
            f", description={item['description']}" if item.get("description") else ""
        )
        recorder_timing = item.get("timing") or "N/A"
        screenshot_index += 1
        image_result = _screenshot_attachment(
            item["screenshot"],
            screenshot_base_dir,
            execution_index,
            task_index,
            {
                "fallbackIdSuffix": f"recorder-{recorder_index + 1}",
                "label": (
                    f"task-{task_index + 1}-{_image_label_suffix(recorder_timing)}"
                ),
                "resolveScreenshotFileName": resolve_screenshot_file_name,
            },
        )
        lines.append(
            f"- #{screenshot_index} type={item.get('type')}, "
            f"ts={_format_time(item.get('ts'))}, timing={recorder_timing}"
            f"{description_text}, id={image_result['attachment']['id']}"
        )
        lines.append(image_result["markdown"])
        attachments.append(image_result["attachment"])

    if screenshot_index > 0:
        return {"lines": lines, "attachments": attachments}
    return {"lines": [], "attachments": attachments}


def _render_execution(
    execution_raw: Any,
    execution_index: int,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution = _to_execution_dump(execution_raw)
    options = options or {}
    screenshot_base_dir = options.get("screenshotBaseDir") or "./screenshots"

    lines: list[str] = []
    attachments: list[dict[str, Any]] = []

    lines.append(f"# {execution['name']}")
    if execution.get("description"):
        lines.extend(["", str(execution["description"])])

    lines.extend(
        [
            "",
            f"- Execution start: {_format_time(execution.get('logTime'))}",
            f"- Task count: {len(execution['tasks'])}",
        ]
    )
    if execution.get("aiActContext"):
        _append_text_section(lines, "AI Action Context", execution["aiActContext"])

    for task_index, task in enumerate(execution["tasks"]):
        title = _type_str(task)
        detail = _safe_task_param(task)
        timing = _resolve_task_timing(task)

        lines.extend(
            [
                "",
                f"## {task_index + 1}. {title}" + (f" - {detail}" if detail else ""),
            ]
        )
        lines.append(f"- Task ID: {task.get('taskId') or 'N/A'}")
        lines.append(f"- Type: {task.get('type') or 'N/A'}")
        lines.append(f"- SubType: {task.get('subType') or 'N/A'}")
        lines.append(f"- Status: {task.get('status') or 'unknown'}")
        lines.append(f"- Start: {_format_time(timing.get('start'))}")
        lines.append(f"- End: {_format_time(timing.get('end'))}")
        cost = timing.get("cost")
        lines.append(
            f"- Cost(ms): {_stringify_number(cost) if isinstance(cost, (int, float)) else 'N/A'}"
        )
        ui_context = task.get("uiContext")
        screen_size = (
            _format_size(ui_context.get("shotSize"))
            if isinstance(ui_context, dict)
            else None
        )
        lines.append("- Screen size: " + (screen_size or "N/A"))

        if task.get("subType") == "Locate":
            locate_center = _extract_locate_center(task)
            if locate_center is not None:
                lines.append(
                    f"- Locate center: ({_stringify_number(locate_center[0])}, "
                    f"{_stringify_number(locate_center[1])})"
                )

        if task.get("errorMessage"):
            lines.append(f"- Error: {task['errorMessage']}")

        usage_rows = _usage_rows_for_task(task)
        if usage_rows:
            lines.extend(["", "### Model Usage"])
            lines.extend(
                _markdown_table(
                    [
                        "Source",
                        "Intent",
                        "Model",
                        "Description",
                        "Prompt Tokens",
                        "Cached Input",
                        "Completion Tokens",
                        "Total Tokens",
                        "Model Call Time(ms)",
                        "Request ID",
                    ],
                    usage_rows,
                )
            )

        _append_json_section(lines, "Param", task.get("param"))
        _append_json_section(lines, "Output", task.get("output"))
        _append_json_section(lines, "Log", task.get("log"))
        _append_text_section(lines, "Thought", task.get("thought"))
        _append_text_section(lines, "Reasoning Content", task.get("reasoning_content"))

        screenshots_section = _screenshots_markdown_section(
            task,
            screenshot_base_dir,
            execution_index,
            task_index,
            options.get("resolveScreenshotFileName"),
        )
        if screenshots_section["lines"]:
            lines.extend(screenshots_section["lines"])
            attachments.extend(screenshots_section["attachments"])

    return {"markdown": "\n".join(lines), "attachments": attachments}


def execution_to_markdown(
    execution: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render one execution as Markdown plus its screenshot attachments."""
    return _render_execution(execution, 0, options)


def report_to_markdown(
    report: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a report as Markdown plus every screenshot attachment."""
    report_dump = _to_report_dump(report)
    options = options or {}

    execution_results = [
        _render_execution(execution, index, options)
        for index, execution in enumerate(report_dump["executions"])
    ]
    attachments = [
        attachment
        for result in execution_results
        for attachment in result["attachments"]
    ]
    report_summary = collect_report_summary(
        report_dump, options.get("wallTimeFallbackMs")
    )
    model_briefs = report_dump.get("modelBriefs") or []
    model_rows = (
        _model_brief_rows(model_briefs)
        if model_briefs
        else _model_rows_from_usage(report_dump)
    )

    model_info_lines = ["\n## Model Info"]
    model_info_lines.extend(
        _markdown_table(["Intent", "Model", "Description"], model_rows)
        if model_rows
        else ["- No model metadata recorded."]
    )

    wall_time_source = report_summary["timing"].get("wallTimeSource")
    if wall_time_source == "task-timestamps":
        elapsed_description = (
            "Total span from the first recorded task start to the last "
            "recorded task end, including model calls, actions, waits, and gaps."
        )
    elif wall_time_source == "fallback":
        elapsed_description = (
            "Total elapsed duration reported by the enclosing test runner "
            "because task timestamps were unavailable."
        )
    else:
        elapsed_description = (
            "The total elapsed span is unavailable because the report has no "
            "recorded task timestamps."
        )
    timing_summary_lines = ["\n## Timing Summary"]
    timing_summary_lines.extend(
        _markdown_table(
            ["Metric", "Duration(ms)", "Definition"],
            [
                [
                    "Elapsed Time",
                    report_summary["timing"].get("wallTimeMs"),
                    elapsed_description,
                ],
                [
                    "Model Call Time",
                    report_summary["timing"].get("modelCallTimeMs"),
                    "Total duration of all recorded model calls.",
                ],
            ],
        )
    )

    token_summary_lines = ["\n## Token Usage Summary"]
    token_summary_lines.extend(
        _markdown_table(
            [
                "Model",
                "Calls",
                "Prompt Tokens",
                "Cached Input",
                "Completion Tokens",
                "Total Tokens",
                "Model Call Time(ms)",
            ],
            [
                [
                    model.get("modelName"),
                    model.get("callCount"),
                    model.get("promptTokens"),
                    model.get("cachedInputTokens"),
                    model.get("completionTokens"),
                    model.get("totalTokens"),
                    model.get("modelCallTimeMs"),
                ]
                for model in report_summary["models"]
            ],
        )
        if report_summary["models"]
        else ["- No token usage recorded."]
    )

    header_parts = [
        f"# {report_dump.get('groupName')}",
        (
            f"\n{report_dump['groupDescription']}"
            if report_dump.get("groupDescription")
            else ""
        ),
        f"\n- SDK Version: {report_dump.get('sdkVersion')}",
        (
            f"- Device Type: {report_dump['deviceType']}"
            if report_dump.get("deviceType")
            else ""
        ),
        f"- Execution count: {len(report_dump['executions'])}",
        *model_info_lines,
        *timing_summary_lines,
        *token_summary_lines,
    ]
    header = "\n".join(part for part in header_parts if part)

    return {
        "markdown": header
        + "\n\n"
        + "\n\n---\n\n".join(result["markdown"] for result in execution_results),
        "attachments": attachments,
    }


def report_file_to_markdown(html_path: str, output_dir: str) -> dict[str, list[str]]:
    """Convert a report HTML into report.md plus externalized screenshots."""
    dump, executions = collect_report_executions(html_path)
    out_dir = Path(output_dir)
    screenshots_dir = out_dir / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: set = set()
    processed = [
        _externalize_images(
            execution,
            None,
            screenshots_dir,
            written,
            {"counter": 0},
            f"execution-{index}",
        )
        for index, execution in enumerate(executions, 1)
    ]
    merged = {key: dump[key] for key in _DUMP_HEADER_KEYS if key in dump}
    merged["executions"] = processed

    md_path = out_dir / "report.md"
    md_path.write_text(report_to_markdown(merged)["markdown"], encoding="utf-8")
    return {
        "markdownFiles": [str(md_path)],
        "screenshotFiles": [str(screenshots_dir / name) for name in sorted(written)],
    }


__all__ = [
    "execution_to_markdown",
    "report_file_to_markdown",
    "report_to_markdown",
]
