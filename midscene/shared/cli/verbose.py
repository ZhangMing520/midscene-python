"""CLI verbose output and progress dispatch (upstream cli/verbose.ts)."""

import json
from datetime import UTC, datetime
from typing import Any, TypeGuard, cast

from midscene.shared.cli.verbose_ai_act import (
    AI_ACT_CLI_PROGRESS_RENDERER,
    CLI_AI_ACT_PROGRESS_SCOPE,
    CliProgressRenderer,
)
from midscene.shared.cli.verbose_screenshot import (
    collect_screenshot_refs,
    render_screenshot_list,
)

CLI_VERBOSE_FLAG = "verbose"

_PROGRESS_EVENT_NAME = "midscene_progress"

_PROGRESS_RENDERERS: dict[str, CliProgressRenderer] = {
    CLI_AI_ACT_PROGRESS_SCOPE: AI_ACT_CLI_PROGRESS_RENDERER,
}

_context: dict[str, dict[str, Any]] = {"current": {"enabled": False}}


def _is_record(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _iso_now() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _parse_verbose_format(raw_format: str) -> str:
    if raw_format in ("text", "jsonl"):
        return raw_format
    raise ValueError(
        f'Unsupported --{CLI_VERBOSE_FLAG} format "{raw_format}". Use '
        f'"--{CLI_VERBOSE_FLAG}" or "--{CLI_VERBOSE_FLAG}=jsonl".'
    )


def strip_verbose_flag(
    argv: list[str],
) -> dict[str, Any]:
    raw_args: list[str] = []
    verbose = False
    verbose_format = "text"

    for arg in argv:
        if arg == f"--{CLI_VERBOSE_FLAG}":
            verbose = True
            continue
        if arg.startswith(f"--{CLI_VERBOSE_FLAG}="):
            verbose = True
            verbose_format = _parse_verbose_format(arg[len(f"--{CLI_VERBOSE_FLAG}=") :])
            continue
        raw_args.append(arg)

    return {"rawArgs": raw_args, "verbose": verbose, "format": verbose_format}


async def with_cli_verbose_context(context: dict[str, Any], fn: Any) -> Any:
    previous = _context["current"]
    _context["current"] = {
        **context,
        "renderedLineKeys": context.get("renderedLineKeys") or set(),
    }
    try:
        return await fn()
    finally:
        _context["current"] = previous


def get_cli_verbose_context() -> dict[str, Any]:
    return _context["current"]


def is_cli_verbose_enabled() -> bool:
    return bool(get_cli_verbose_context().get("enabled"))


def _progress_renderer_for_event(
    event: Any,
) -> dict[str, Any] | None:
    if not _is_record(event):
        return None
    scope = event.get("scope")
    if not isinstance(scope, str):
        return None
    renderer = _PROGRESS_RENDERERS.get(scope)
    return {"scope": scope, "renderer": renderer} if renderer else None


def emit_cli_verbose_event(event: dict[str, Any]) -> None:
    context = get_cli_verbose_context()
    if not context.get("enabled"):
        return

    payload = {
        key: value
        for key, value in {
            "type": _PROGRESS_EVENT_NAME,
            "timestamp": _iso_now(),
            "scriptName": context.get("scriptName"),
            "command": context.get("commandName"),
            **event,
        }.items()
        if value is not None
    }

    if context.get("format") == "jsonl":
        print(json.dumps(payload, ensure_ascii=False))
        return

    text = _render_cli_verbose_event_text(payload, context)
    if text:
        print(text)


def cli_verbose_error_message(error: Any) -> str:
    return str(error) if isinstance(error, BaseException) else str(error)


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


def _compact_primitive(value: Any) -> dict[str, Any]:
    if value is None:
        return {"handled": True, "value": value}
    if isinstance(value, str):
        return {
            "handled": True,
            "value": f"{value[:177]}..." if len(value) > 180 else value,
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"handled": True, "value": value}
    if isinstance(value, bool):
        return {"handled": True, "value": value}
    if not isinstance(value, (dict, list)):
        return {"handled": True, "value": str(value)}
    return {"handled": False}


def _compact_structured_value(value: Any) -> Any:
    primitive = _compact_primitive(value)
    if primitive["handled"]:
        return primitive["value"]
    if isinstance(value, list):
        return [_compact_structured_value(item) for item in value[:5]]
    if not _is_record(value):
        return str(value)
    return {
        key: _compact_structured_value(entry_value)
        for key, entry_value in list(value.items())[:6]
    }


def compact_cli_verbose_value(value: Any) -> Any:
    primitive = _compact_primitive(value)
    if primitive["handled"]:
        return primitive["value"]
    if isinstance(value, list):
        return [compact_cli_verbose_value(item) for item in value[:5]]
    if _is_record(value) and isinstance(value.get("prompt"), str):
        return compact_cli_verbose_value(value["prompt"])
    if not _is_record(value):
        return str(value)
    return {
        key: compact_cli_verbose_value(entry_value)
        for key, entry_value in list(value.items())[:6]
    }


def compact_cli_verbose_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _compact_structured_value(value) for key, value in list(args.items())[:8]
    }


def _summarize_param(param: Any) -> Any:
    if not param or not isinstance(param, dict):
        return compact_cli_verbose_value(param)
    if isinstance(param.get("prompt"), str):
        return compact_cli_verbose_value(param["prompt"])
    locate = param.get("locate")
    if isinstance(locate, dict):
        return {
            "locate": compact_cli_verbose_value(locate.get("prompt")),
            **{
                key: compact_cli_verbose_value(value)
                for key, value in list(param.items())[:4]
                if key != "locate"
            },
        }
    return compact_cli_verbose_value(param)


def _summarize_user_instruction(value: Any) -> str:
    if isinstance(value, str):
        return _compact_text(value)
    if _is_record(value) and isinstance(value.get("prompt"), str):
        return _compact_text(value["prompt"])
    return _compact_text(value)


def _summarize_task_param_text(task: dict[str, Any]) -> str:
    param = task.get("param")
    if not _is_record(param):
        return _compact_text(_summarize_param(param))
    if task.get("type") == "Planning" and task.get("subType") != "Locate":
        if param.get("userInstructionDisplay"):
            return _summarize_user_instruction(param["userInstructionDisplay"])
        if param.get("userInstruction"):
            return _summarize_user_instruction(param["userInstruction"])
    if param.get("dataDemand"):
        return _compact_text(_summarize_param(param["dataDemand"]))
    if param.get("assertion"):
        return _compact_text(_summarize_param(param["assertion"]))
    return _compact_text(_summarize_param(param))


def _summarize_sub_goals(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    goals = []
    for goal in value[:6]:
        if not _is_record(goal):
            continue
        index = f"{goal['index']}. " if isinstance(goal.get("index"), int) else ""
        status = f"[{goal['status']}] " if isinstance(goal.get("status"), str) else ""
        description = (
            goal.get("description") if isinstance(goal.get("description"), str) else ""
        )
        text = f"{index}{status}{description}".strip()
        if text:
            goals.append(text)
    return f"sub-goals: {'; '.join(goals)}" if goals else ""


def _summarize_actions(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    actions = []
    for action in value[:5]:
        if not _is_record(action):
            continue
        type_name = (
            action.get("type") if isinstance(action.get("type"), str) else "Action"
        )
        param = _compact_text(_summarize_param(action.get("param")))
        text = f"{type_name}: {param}" if param else type_name
        if text:
            actions.append(text)
    return f"actions: {'; '.join(actions)}" if actions else ""


def _summarize_task_output_text(task: dict[str, Any]) -> str:
    output = task.get("output")
    if not _is_record(output):
        return _compact_text(output)
    return (
        _summarize_sub_goals(output.get("updateSubGoals"))
        or _compact_text(output.get("log"))
        or _compact_text(output.get("output"))
        or _summarize_actions(output.get("actions"))
    )


def _summarize_task_text(task: dict[str, Any]) -> str:
    parts = [
        part
        for part in (task.get("type"), task.get("subType"))
        if isinstance(part, str) and part
    ]
    label = "/".join(parts) if parts else "Task"
    status = (
        task.get("status")
        if isinstance(task.get("status"), str) and task["status"]
        else "unknown"
    )
    param = _summarize_task_param_text(task)
    output = _summarize_task_output_text(task)
    thought = _compact_text(task.get("thought"))
    detail = output or thought or param
    return f"{label} {status}: {detail}" if detail else f"{label} {status}"


def _summarize_dump_update(
    execution_dump: Any,
    screenshot_options: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    options = screenshot_options or {}
    if not _is_record(execution_dump) or not isinstance(
        execution_dump.get("tasks"), list
    ):
        return None

    tasks = execution_dump["tasks"]
    latest_task = tasks[-1] if tasks else None
    steps = []
    for index, task in enumerate(tasks):
        if not _is_record(task):
            continue
        timing = task.get("timing")
        duration = timing.get("cost") if isinstance(timing, dict) else None
        steps.append(
            {
                "id": task.get("taskId"),
                "index": index + 1,
                "total": len(tasks),
                "type": task.get("type"),
                "subType": task.get("subType"),
                "status": task.get("status"),
                "param": _summarize_param(task.get("param")),
                "message": _summarize_task_text(task),
                "error": task.get("errorMessage"),
                "durationMs": duration,
                "screenshots": collect_screenshot_refs(task, options)[-3:],
            }
        )

    latest = None
    if _is_record(latest_task):
        timing = latest_task.get("timing")
        duration = timing.get("cost") if isinstance(timing, dict) else None
        latest = {
            "id": latest_task.get("taskId"),
            "index": len(tasks),
            "total": len(tasks),
            "type": latest_task.get("type"),
            "subType": latest_task.get("subType"),
            "status": latest_task.get("status"),
            "param": _summarize_param(latest_task.get("param")),
            "message": _summarize_task_text(latest_task),
            "error": latest_task.get("errorMessage"),
            "durationMs": duration,
        }

    return {
        "execution": {
            "id": execution_dump.get("id"),
            "name": execution_dump.get("name"),
            "description": compact_cli_verbose_value(execution_dump.get("description")),
            "taskCount": len(tasks),
        },
        "steps": steps,
        "task": latest,
        "screenshots": collect_screenshot_refs(tasks, options)[-5:],
    }


def _stringify_args(args: Any) -> str:
    if not _is_record(args) or not args:
        return ""
    return ", ".join(f"{key}={_compact_text(value)}" for key, value in args.items())


def _is_act_verbose_event(command: str | None, tool: str | None) -> bool:
    return command == "act" or tool == "act"


def _render_lines_once(
    context: dict[str, Any], lines: list[dict[str, str]]
) -> str | None:
    if not lines:
        return None
    rendered_line_keys = context.get("renderedLineKeys")
    if rendered_line_keys is None:
        rendered_line_keys = set()
        context["renderedLineKeys"] = rendered_line_keys
    # The context owns this set; callers only read or replace it through helpers.
    rendered_keys = cast(set[str], rendered_line_keys)
    pending = []
    for line in lines:
        if line["key"] in rendered_keys:
            continue
        rendered_keys.add(line["key"])
        pending.append(line["text"])
    return "\n".join(pending) if pending else None


def _render_cli_verbose_event_text(
    event: dict[str, Any], context: dict[str, Any]
) -> str | None:
    command = (
        event.get("command") if isinstance(event.get("command"), str) else "command"
    )
    tool = event.get("tool") if isinstance(event.get("tool"), str) else None
    event_name = event.get("event")

    if event_name == "agent_progress":
        scope = event.get("scope") if isinstance(event.get("scope"), str) else None
        renderer = _PROGRESS_RENDERERS.get(scope) if scope else None
        progress_event = (
            event.get("progress") if _is_record(event.get("progress")) else None
        )
        if not renderer or not progress_event:
            return None
        return _render_lines_once(context, renderer.build_lines(progress_event))
    if event_name == "command_start":
        if _is_act_verbose_event(command, tool):
            return None
        args = _stringify_args(event.get("args"))
        return (
            f"[Midscene] {command} started ({args})"
            if args
            else f"[Midscene] {command} started"
        )
    if event_name == "agent_ready":
        if _is_act_verbose_event(command, tool):
            return None
        return f"[Midscene] {tool or command} ready"
    if event_name == "recording_ready":
        return "[Midscene] Recording. Press Ctrl+C to stop and save."
    if event_name == "recording_stopping":
        reason = event.get("reason")
        if reason == "watchdog":
            return "[Midscene] Recording watchdog reached; finalizing and saving."
        if reason == "sigterm":
            return "[Midscene] SIGTERM received; finalizing and saving."
        if reason == "sighup":
            return "[Midscene] SIGHUP received; finalizing and saving."
        return (
            "[Midscene] Ctrl+C received; finalizing and saving. Press Ctrl+C "
            "again to force exit."
        )
    if event_name == "dump_update":
        if _is_act_verbose_event(command, tool):
            return None
        task = event.get("task") if _is_record(event.get("task")) else None
        raw_steps = event.get("steps")
        steps = (
            [step for step in raw_steps if _is_record(step)]
            if isinstance(raw_steps, list)
            else []
        )
        execution = (
            event.get("execution") if _is_record(event.get("execution")) else None
        )
        execution_name = (
            execution.get("name")
            if execution and isinstance(execution.get("name"), str)
            else "execution"
        )
        if steps:
            lines = [f"[Midscene] Progress: {execution_name} ({len(steps)} steps)"]
            for step in steps:
                index = (
                    f"Step {step.get('index')}/{step.get('total')}"
                    if isinstance(step.get("index"), int)
                    and isinstance(step.get("total"), int)
                    else "Step"
                )
                message = (
                    step.get("message")
                    if isinstance(step.get("message"), str)
                    else step.get("status")
                    if isinstance(step.get("status"), str)
                    else "updated"
                )
                lines.append(f"[Midscene] {index}: {message}")
        else:
            message = (
                task.get("message")
                if task and isinstance(task.get("message"), str)
                else task.get("status")
                if task and isinstance(task.get("status"), str)
                else "updated"
            )
            lines = [f"[Midscene] Step: {message}"]
        screenshots = render_screenshot_list(event.get("screenshots"))
        if screenshots:
            lines.append(f"[Midscene] Screenshot: {screenshots}")
        report = event.get("report")
        if isinstance(report, str) and report:
            lines.append(f"[Midscene] Report: {report}")
        return "\n".join(lines)
    if event_name == "artifact":
        if _is_act_verbose_event(command, tool):
            return None
        kind = event.get("kind") if isinstance(event.get("kind"), str) else "artifact"
        path = event.get("path") if isinstance(event.get("path"), str) else None
        return (
            f"[Midscene] {kind} saved: {path}" if path else f"[Midscene] {kind} ready"
        )
    if event_name == "command_done":
        if _is_act_verbose_event(command, tool):
            if event.get("status") == "error":
                error = (
                    f": {event['error']}"
                    if isinstance(event.get("error"), str) and event["error"]
                    else ""
                )
                return _render_lines_once(
                    context,
                    [
                        {
                            "key": f"aiAct:command_failed:{event.get('error') or 'unknown'}",
                            "text": f"[Midscene][aiAct] Failed{error}",
                        }
                    ],
                )
            return None
        status = "failed" if event.get("status") == "error" else "finished"
        duration = (
            f" in {event['durationMs']}ms"
            if isinstance(event.get("durationMs"), (int, float))
            and not isinstance(event.get("durationMs"), bool)
            else ""
        )
        error = (
            f": {event['error']}"
            if event.get("status") == "error" and isinstance(event.get("error"), str)
            else ""
        )
        return f"[Midscene] {command} {status}{duration}{error}"
    return None


def attach_cli_verbose_dump_listener(
    agent: Any, options: dict[str, Any] | None = None
) -> Any:
    options = options or {}
    if not is_cli_verbose_enabled():
        return lambda: None

    is_act_tool = options.get("toolName") == "act"
    screenshot_export_cache: dict[str, str] = {}

    add_progress_listener = getattr(agent, "add_progress_listener", None)
    if is_act_tool and add_progress_listener is not None:

        def on_progress(event: Any) -> None:
            match = _progress_renderer_for_event(event)
            if not match:
                return
            context = get_cli_verbose_context()
            is_text_mode = context.get("format") != "jsonl"
            progress = match["renderer"].normalize(
                event,
                {
                    "reportFile": getattr(agent, "report_file", None),
                    "exportMode": "report" if is_text_mode else "none",
                    "cache": screenshot_export_cache,
                },
            )
            if not progress:
                return
            emit_cli_verbose_event(
                {
                    "event": "agent_progress",
                    "tool": options.get("toolName"),
                    "scope": match["scope"],
                    "progress": progress,
                }
            )

        return add_progress_listener(on_progress)

    if is_act_tool:
        return lambda: None

    add_dump_update_listener = getattr(agent, "add_dump_update_listener", None)
    if add_dump_update_listener is None:
        return lambda: None

    def on_dump_update(_dump: str, execution_dump: Any = None) -> None:
        context = get_cli_verbose_context()
        is_text_mode = context.get("format") != "jsonl"
        summary_export_mode = "tmp" if is_text_mode and not is_act_tool else "none"
        summary = _summarize_dump_update(
            execution_dump,
            {"exportMode": summary_export_mode, "cache": screenshot_export_cache},
        )
        if not summary:
            return
        emit_cli_verbose_event(
            {
                "event": "dump_update",
                "tool": options.get("toolName"),
                "report": getattr(agent, "report_file", None) or None,
                **summary,
            }
        )

    return add_dump_update_listener(on_dump_update)


__all__ = [
    "CLI_VERBOSE_FLAG",
    "attach_cli_verbose_dump_listener",
    "cli_verbose_error_message",
    "compact_cli_verbose_args",
    "compact_cli_verbose_value",
    "emit_cli_verbose_event",
    "get_cli_verbose_context",
    "is_cli_verbose_enabled",
    "strip_verbose_flag",
    "with_cli_verbose_context",
]
