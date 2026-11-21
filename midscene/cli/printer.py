"""Console output for batch and single-script runs (upstream printer.ts)."""


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
