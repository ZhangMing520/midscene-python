"""Console output for batch and single-script runs (upstream printer.ts)."""

import os
import sys
import time
from typing import Any, List, Mapping, Optional

indent = "  "
spinner_interval = 80
spinner_frames = ["◰", "◳", "◲", "◱"]


def _colorize(code: str, text: str) -> str:
    if not is_tty or os.environ.get("NO_COLOR"):
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _gray(text: str) -> str:
    return _colorize("90", text)


def _yellow_bright(text: str) -> str:
    return _colorize("93", text)


def _green(text: str) -> str:
    return _colorize("32", text)


def _red(text: str) -> str:
    return _colorize("31", text)


def resolve_is_tty(
    env: Optional[Mapping[str, str]] = None,
    stdout_is_tty: Optional[bool] = None,
) -> bool:
    """Decide whether the interactive spinner renderer is safe to use.

    Besides a real TTY, honor well-known non-interactive signals so CI
    pipelines do not get flooded with cursor-control sequences.
    """
    env = os.environ if env is None else env
    if stdout_is_tty is None:
        stdout_is_tty = bool(
            getattr(sys.stdout, "isatty", lambda: False)()
        )
    if (
        env.get("MIDSCENE_CLI_LOG_ON_NON_TTY")
        or env.get("NO_COLOR")
        or env.get("TERM") == "dumb"
        or env.get("CI")
    ):
        return False
    return bool(stdout_is_tty)


is_tty = resolve_is_tty()


def current_spinning_frame() -> str:
    """The spinner frame for the current wall-clock moment (upstream)."""
    index = int(time.time() * 1000 // spinner_interval) % len(spinner_frames)
    return spinner_frames[index]


def _indicator_for_status(status: Any) -> str:
    if status == "init":
        return _gray("◌")
    if status == "running":
        return _yellow_bright(current_spinning_frame())
    if status == "done":
        return _green("✔︎")
    if status == "error":
        return _red("✘")
    return ""


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def context_info(context: Mapping[str, Any]) -> dict:
    """Compose the status block for one YAML file (upstream contextInfo)."""
    player = context.get("player")
    file_path = context.get("file")
    file_path_to_show = os.path.relpath(str(file_path), os.getcwd())
    file_name_to_print = _gray(file_path_to_show)
    status = _field(player, "status", default="init")
    file_status_text = _indicator_for_status(status)

    current_task_index = _field(player, "currentTaskIndex", "current_task_index")
    context_action_text = (
        _gray("(navigating)")
        if current_task_index is None and status == "running"
        else ""
    )

    error_in_setup = _field(player, "errorInSetup", "error_in_setup")
    error_text = ""
    if error_in_setup:
        message = _field(error_in_setup, "message", default=str(error_in_setup))
        stack = _field(error_in_setup, "stack", default="")
        error_text = (
            f"\n{indent}{_red('error:')} {message}"
            f"\n{indent}{indent}{stack}"
        )

    output_file = _field(player, "output", "output_path")
    player_result = _field(player, "result", default={})
    output_text = (
        f"\n{indent}{_gray(f'output: {output_file}')}"
        if output_file and player_result
        else ""
    )

    report_file = _field(player, "reportFile", "report_file")
    report_text = (
        f"\n{indent}{_gray(f'report: {report_file}')}" if report_file else ""
    )

    agent_status_tip = _field(player, "agentStatusTip", "agent_status_tip")
    agent_status_text = (
        f"\n{indent}{_gray(f'agent status: {agent_status_tip}')}"
        if agent_status_tip
        else ""
    )

    merged_text = (
        f"{file_status_text} {file_name_to_print} {context_action_text}"
        f"{output_text}{report_text}{error_text}{agent_status_text}"
    ).strip()

    return {
        "fileNameToPrint": file_name_to_print,
        "fileStatusText": file_status_text,
        "contextActionText": context_action_text,
        "outputText": output_text,
        "reportText": report_text,
        "mergedText": merged_text,
    }


def single_task_info(task: Any) -> dict:
    """Compose the status line for one task (upstream singleTaskInfo)."""
    status = _field(task, "status", default="init")
    name = _field(task, "name", default="")
    step_text = ""
    if status == "init":
        step_text = ""
    elif status in ("running", "error"):
        current_step = _field(task, "currentStep", "current_step")
        if current_step is None:
            step_text = _gray("(navigating)")
        elif isinstance(current_step, int):
            total_steps = _field(task, "totalSteps", "total_steps")
            step_text = _gray(
                f"(task {current_step + 1}/{total_steps})".strip()
            )
        else:
            step_text = _gray("(unknown task)")

    error = _field(task, "error")
    error_text = ""
    if status == "error":
        error_message = _field(error, "message", default=error or "")
        error_text = (
            f"\n{indent}{_gray('error:')}\n{indent}{indent}{error_message}"
        )

    status_text = _indicator_for_status(status)
    merged_line = f"{status_text} {name} {step_text}{error_text}"
    return {
        "nameText": name,
        "stepText": step_text,
        "errorText": error_text,
        "itemStatusText": status_text,
        "mergedLine": merged_line,
    }


def _padding_lines(lines: List[str]) -> List[str]:
    return [f"{indent}{line}" for line in lines]


def context_task_list_summary(
    task_status_array: List[Any], context: Mapping[str, Any]
) -> str:
    """Render a file header plus its task lines (upstream contextTaskListSummary)."""
    player = context.get("player")
    status = _field(player, "status", default="init")
    prefix_lines: List[str] = []
    current_line: List[str] = []
    suffix_text: List[str] = []

    file_info = context_info(context)["mergedText"]
    if not _field(player, "errorInSetup", "error_in_setup"):
        for task in task_status_array:
            merged_line = single_task_info(task)["mergedLine"]
            if status == "init":
                suffix_text.append(merged_line)
            elif status == "running":
                current_line.append(merged_line)
            elif status in ("done", "error"):
                prefix_lines.append(merged_line)

    lines = [file_info]
    if prefix_lines:
        lines.extend(_padding_lines(prefix_lines))
    if current_line:
        lines.extend(_padding_lines(current_line))
    if suffix_text:
        lines.extend(_padding_lines(suffix_text))
    return "\n".join(lines)


def format_yaml_progress_snapshot(
    message: str, attempt: int, total_attempts: int
) -> str:
    """Prefix progress with the attempt number when retries are enabled."""
    if total_attempts > 1:
        return f"Attempt {attempt}/{total_attempts}\n{message}"
    return message


def print_batch_results(console, results, runner) -> None:
    """Print one line per batch result (upstream printer)."""
    for result in results:
        status = "[green]PASS[/green]" if result["success"] else "[red]FAIL[/red]"
        extra = f" ({result.get('resultType')})" if not result["executed"] else ""
        console.print(f"{status} {result['file']}{extra}")


def print_script_result(console, player) -> None:
    """Print the output path and failed tasks of a single YAML run."""
    if player.output_path:
        console.print(f"[green]Output written to: {player.output_path}[/green]")
    for task in player.failed_tasks:
        console.print(f"[red]task - {task['name']}: {task['error']}[/red]")
