"""Model connectivity commands (upstream packages/cli/src/model-command.ts)."""

import asyncio

from rich.console import Console


def run_model_connect(console: Console) -> bool:
    """Run the model connectivity test (text / vision / aiLocate)."""
    from midscene.core.ai_model.connectivity import run_connectivity_test
    from midscene.shared.env import ModelConfigManager

    async def _run():
        manager = ModelConfigManager()
        result = await run_connectivity_test(
            {
                "defaultModelConfig": manager.get_model_config("default"),
                "locateModelConfig": manager.get_model_config("locate"),
                "planningModelConfig": manager.get_model_config("planning"),
                "insightModelConfig": manager.get_model_config("insight"),
            }
        )
        return result

    result = asyncio.run(_run())
    for check in result["checks"]:
        status = "[green]PASS[/green]" if check["passed"] else "[red]FAIL[/red]"
        console.print(
            f"{status} {check['name']} ({check['intent']}) - {check['modelName']} "
            f"({check.get('modelFamily') or 'default'}) - {check['durationMs']}ms"
        )
    if result["passed"]:
        console.print("[green]All connectivity checks passed[/green]")
        return True
    console.print(f"[red]{result.get('message', '')}[/red]")
    return False


def run_model_verify(console: Console) -> bool:
    """Alias of `model connect` (upstream `midscene model verify`)."""
    return run_model_connect(console)
