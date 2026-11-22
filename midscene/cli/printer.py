"""Console output for batch and single-script runs (upstream printer.ts)."""

import os
import sys
from typing import Mapping, Optional


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
