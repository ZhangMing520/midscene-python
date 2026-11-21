"""aiAct-specific verbose progress rendering (upstream verbose-ai-act.ts)."""

import json
import math
from typing import Any, Callable, Dict, List, Optional

from midscene.shared.cli.verbose_screenshot import (
    collect_screenshot_refs,
    path_for_report_screenshot,
)

CLI_AI_ACT_PROGRESS_SCOPE = "aiAct"

CliVerboseLine = Dict[str, str]


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _compact_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return f"{value[:177]}..." if len(value) > 180 else value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return f"{encoded[:177]}..." if len(encoded) > 180 else encoded
    except (TypeError, ValueError):
        return str(value)


def _numeric_value(value: Any) -> Optional[float]:
    return (
        float(value)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _first_text(values: List[Any]) -> str:
    for value in values:
        text = _compact_text(value)
        if text:
            return text
    return ""


def _plan_prefix(event: Dict[str, Any]) -> str:
    plan_index = _numeric_value(event.get("planIndex"))
    if not plan_index:
        return "[Midscene][aiAct]"
    plan_limit = _numeric_value(event.get("planLimit"))
    suffix = f"/{round(plan_limit)}" if plan_limit else ""
    return f"[Midscene][aiAct][Plan {round(plan_index)}{suffix}]"


def _event_key(event: Dict[str, Any], suffix: str) -> str:
    sequence = _numeric_value(event.get("sequence"))
    if sequence:
        return f"aiAct:{int(sequence)}:{suffix}"
    return ":".join(
        part
        for part in (
            "aiAct",
            _compact_text(event.get("phase")),
            _compact_text(event.get("planIndex")),
            suffix,
        )
        if part
    )


def _integer_text(value: float) -> str:
    return str(round(value))


def _number_tuple(value: Any, size: int) -> Optional[List[float]]:
    if (
        isinstance(value, list)
        and len(value) >= size
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value[:size]
        )
    ):
        return [float(item) for item in value[:size]]
    return None


def _parse_action(value: Any) -> Optional[Dict[str, Any]]:
    if not _is_record(value) or not isinstance(value.get("name"), str):
        return None
    return {
        "name": value["name"],
        "target": value.get("target") if isinstance(value.get("target"), str) else None,
        "point": _number_tuple(value.get("point"), 2),
        "bbox": _number_tuple(value.get("bbox"), 4),
        "param": value.get("param"),
    }


def _format_point(point: List[float]) -> str:
    return f"({_integer_text(point[0])}, {_integer_text(point[1])})"


def _format_bbox(bbox: List[float]) -> str:
    return "(" + ",".join(_integer_text(item) for item in bbox) + ")"


def _sleep_action_text(action: Dict[str, Any]) -> Optional[str]:
    if action["name"] != "Sleep" or not _is_record(action.get("param")):
        return None
    param = action["param"]
    time_ms = (
        _numeric_value(param.get("timeMs"))
        or _numeric_value(param.get("duration"))
        or _numeric_value(param.get("timeoutMs"))
    )
    return f"Sleep {_integer_text(time_ms)}ms" if time_ms is not None else None


def _planned_action_text(action: Dict[str, Any]) -> str:
    if action.get("point"):
        target_segment = f' "{action["target"]}"' if action.get("target") else ""
        bbox_segment = f", bbox={_format_bbox(action['bbox'])}" if action.get("bbox") else ""
        return (
            f"{action['name']}{target_segment} at "
            f"{_format_point(action['point'])}{bbox_segment}"
        )
    sleep = _sleep_action_text(action)
    if sleep:
        return sleep
    param_text = _compact_text(action.get("param"))
    return f"{action['name']}: {param_text}" if param_text else action["name"]


def _running_action_text(action: Dict[str, Any]) -> str:
    if action.get("point"):
        return f"{action['name']} at {_format_point(action['point'])}"
    return _planned_action_text(action)


def normalize_ai_act_progress_event_for_cli(
    event: Any, screenshot_options: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    options = screenshot_options or {}
    if not _is_record(event) or event.get("scope") != CLI_AI_ACT_PROGRESS_SCOPE:
        return None

    data = event.get("data") if _is_record(event.get("data")) else {}
    screenshots = collect_screenshot_refs(data.get("screenshot"), options)
    latest_path = next(
        (
            item.get("path")
            for item in reversed(screenshots)
            if isinstance(item.get("path"), str) and item["path"]
        ),
        None,
    )
    screenshot_path = (
        path_for_report_screenshot(latest_path, options.get("reportFile"))
        if latest_path
        else None
    )

    payload: Dict[str, Any] = {
        "phase": event.get("phase"),
        "sequence": event.get("sequence"),
        "prompt": data.get("prompt"),
        "planIndex": data.get("planIndex"),
        "planLimit": data.get("planLimit"),
        "action": data.get("action"),
        "thought": data.get("thought"),
        "log": data.get("log"),
        "output": data.get("output"),
        "durationMs": data.get("durationMs"),
        "error": data.get("error"),
    }
    if screenshots:
        payload["screenshots"] = screenshots
    if screenshot_path:
        payload["screenshotPath"] = screenshot_path
    return payload


def build_ai_act_progress_event_lines(
    event: Dict[str, Any],
) -> List[CliVerboseLine]:
    phase = event.get("phase") if isinstance(event.get("phase"), str) else ""
    prefix = _plan_prefix(event)
    error = _compact_text(event.get("error"))
    duration = (
        f" cost={round(event['durationMs'])}ms"
        if isinstance(event.get("durationMs"), (int, float))
        and not isinstance(event.get("durationMs"), bool)
        else ""
    )
    action = _parse_action(event.get("action"))

    if phase == "start":
        prompt = _compact_text(event.get("prompt"))
        return [
            {
                "key": f"aiAct:start:{prompt}",
                "text": f"[Midscene][aiAct] Start: {prompt}"
                if prompt
                else "[Midscene][aiAct] Start",
            }
        ]
    if phase == "plan_thinking":
        if event.get("screenshotPath"):
            return [
                {
                    "key": _event_key(event, "thinking"),
                    "text": (
                        f"{prefix} Thinking with the latest screenshot: "
                        f"{event['screenshotPath']}"
                    ),
                }
            ]
        return [
            {
                "key": _event_key(event, "thinking"),
                "text": f"{prefix} Thinking with the latest screenshot",
            }
        ]
    if phase == "plan_planned":
        text = _first_text(
            [event.get("log"), event.get("thought"), event.get("output")]
        )
        return (
            [{"key": _event_key(event, "planned"), "text": f"{prefix} Planned: {text}"}]
            if text
            else []
        )
    if phase == "plan_action":
        return (
            [
                {
                    "key": _event_key(event, "action"),
                    "text": f"{prefix} Action: {_planned_action_text(action)}",
                }
            ]
            if action
            else []
        )
    if phase == "plan_failed":
        return [
            {
                "key": _event_key(event, "plan_failed"),
                "text": f"{prefix} Failed{': ' + error if error else ''}",
            }
        ]
    if phase == "action_running":
        return (
            [
                {
                    "key": _event_key(event, "action_running"),
                    "text": (
                        "[Midscene][aiAct][Action] Running: "
                        f"{_running_action_text(action)}"
                    ),
                }
            ]
            if action
            else []
        )
    if phase == "action_done":
        return (
            [
                {
                    "key": _event_key(event, "action_done"),
                    "text": (
                        f"[Midscene][aiAct][Action] Done: {action['name']}{duration}"
                    ),
                }
            ]
            if action
            else []
        )
    if phase == "action_failed":
        return [
            {
                "key": _event_key(event, "action_failed"),
                "text": (
                    "[Midscene][aiAct][Action] Failed"
                    f"{': ' + action['name'] if action else ''}{duration}"
                    f"{' error=' + error if error else ''}"
                ),
            }
        ]
    if phase == "complete":
        text = _first_text(
            [event.get("output"), event.get("log"), event.get("thought")]
        )
        return [
            {
                "key": _event_key(event, "complete"),
                "text": f"[Midscene][aiAct] Complete{': ' + text if text else ''}",
            }
        ]
    if phase == "failed":
        return [
            {
                "key": _event_key(event, "failed"),
                "text": f"[Midscene][aiAct] Failed{': ' + error if error else ''}",
            }
        ]
    return []


class CliProgressRenderer:
    """Producer-specific renderer for the generic CLI progress dispatcher."""

    def __init__(
        self,
        normalize: Callable[..., Optional[Dict[str, Any]]],
        build_lines: Callable[[Dict[str, Any]], List[CliVerboseLine]],
    ) -> None:
        self.normalize = normalize
        self.build_lines = build_lines


AI_ACT_CLI_PROGRESS_RENDERER = CliProgressRenderer(
    normalize_ai_act_progress_event_for_cli,
    build_ai_act_progress_event_lines,
)


__all__ = [
    "AI_ACT_CLI_PROGRESS_RENDERER",
    "CLI_AI_ACT_PROGRESS_SCOPE",
    "CliProgressRenderer",
    "build_ai_act_progress_event_lines",
    "normalize_ai_act_progress_event_for_cli",
]
