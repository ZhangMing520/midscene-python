"""
Midscene CLI entry point (upstream packages/cli/src/index.ts).

`midscene run` executes YAML automation scripts; `midscene model siwc login`
performs ChatGPT (SIWC) sign-in; `midscene model connect` runs the model
connectivity test.

``midscene.cli.main`` remains as a compatibility re-export of this module.
"""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from midscene.cli.args import (
    _TARGET_KEYS,
    _kebab_to_camel,
    _merge_cli_target_overrides,
    _normalize_cli_value,
    _parse_cli_target_overrides,
)
from midscene.cli.cli_utils import (
    _SERVE_SERVERS,
    _is_batch_config,
    _keep_window,
    _read_batch_config,
    _resolve_served_url,
    _start_static_server,
)
from midscene.cli.config_factory import _build_agent_options, _extract_cache_id
from midscene.cli.create_yaml_player import (
    create_agent_for_script as _create_agent_for_script,
)
from midscene.cli.dotenv_loader import _load_dotenv
from midscene.cli.execution_summary import run_report_tool
from midscene.cli.model_command import run_model_connect, run_model_verify
from midscene.cli.printer import print_batch_results, print_script_result
from midscene.cli.siwc_command import run_siwc_login, run_siwc_refresh

__all__ = [
    "app",
    "model_app",
    "siwc_app",
    "console",
    "run",
    "siwc_login",
    "siwc_refresh",
    "model_connect",
    "model_verify",
    "report_tool",
    "version",
    "main",
    "_TARGET_KEYS",
    "_kebab_to_camel",
    "_normalize_cli_value",
    "_parse_cli_target_overrides",
    "_merge_cli_target_overrides",
    "_build_agent_options",
    "_extract_cache_id",
    "_SERVE_SERVERS",
    "_read_batch_config",
    "_is_batch_config",
    "_start_static_server",
    "_resolve_served_url",
    "_create_agent_for_script",
    "_load_dotenv",
    "_keep_window",
]

app = typer.Typer(
    name="midscene",
    help="AI-powered automation framework for Web, Android, and Desktop platforms",
    no_args_is_help=True,
)
model_app = typer.Typer(name="model", help="Model configuration and diagnostics")
app.add_typer(model_app, name="model")
siwc_app = typer.Typer(name="siwc", help="Sign-In with ChatGPT (SIWC) auth")
model_app.add_typer(siwc_app, name="siwc")

console = Console()


@app.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
def run(
    ctx: typer.Context,
    script_path: Optional[str] = typer.Argument(None, help="Path to YAML script file"),
    headed: bool = typer.Option(False, "--headed", help="Run browser in headed mode"),
    device_id: Optional[str] = typer.Option(
        None, "--device", "-d", help="Android device ID"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    files: Optional[list[str]] = typer.Option(
        None, "--files", help="YAML files to run"
    ),
    config_file: Optional[str] = typer.Option(
        None, "--config", help="Batch config YAML path"
    ),
    setup: Optional[str] = typer.Option(
        None, "--setup", help="A YAML file to run before the main files"
    ),
    summary: Optional[str] = typer.Option(
        None, "--summary", help="Path for the summary output file"
    ),
    artifact_dir: Optional[str] = typer.Option(
        None,
        "--artifact-dir",
        help="Write a directory report artifact (report.json + data/)",
    ),
    namespace: Optional[str] = typer.Option(
        None, "--namespace", help="Name for the report artifact group"
    ),
    concurrent: Optional[int] = typer.Option(
        None, "--concurrent", help="Number of concurrent executions"
    ),
    retry: Optional[int] = typer.Option(
        None, "--retry", help="Retry count for failed YAML files"
    ),
    continue_on_error: Optional[bool] = typer.Option(
        None,
        "--continue-on-error/--no-continue-on-error",
        help="Continue execution even if some tasks fail",
    ),
    share_browser_context: Optional[bool] = typer.Option(
        None,
        "--share-browser-context/--no-share-browser-context",
        help="Share a browser context across multiple YAML files",
    ),
    reuse_page: Optional[bool] = typer.Option(
        None,
        "--reuse-page/--no-reuse-page",
        help="Reuse one page across sequential YAML files",
    ),
    keep_window: bool = typer.Option(
        False, "--keep-window", help="Keep the browser window open after the run"
    ),
    dotenv_override: bool = typer.Option(
        False, "--dotenv-override", help=".env values override the environment"
    ),
    dotenv_debug: bool = typer.Option(
        False, "--dotenv-debug", help="Log .env loading decisions"
    ),
):
    """Run a YAML script, a directory of scripts, or a batch config
    (upstream `midscene run`)."""
    from midscene.core.agent.agent import Agent
    from midscene.core.yaml import ScriptPlayer, parse_yaml_script

    if verbose:
        from midscene.shared.logger import setup_logger

        setup_logger(level="DEBUG")

    _load_dotenv(dotenv_override, dotenv_debug)
    target_overrides = _parse_cli_target_overrides(list(ctx.args))

    def _apply_batch_flags(batch_config: dict) -> dict:
        for key, value in (
            ("setup", setup),
            ("summary", summary),
            ("artifactDir", artifact_dir),
            ("namespace", namespace),
            ("concurrent", concurrent),
            ("retry", retry),
            ("continueOnError", continue_on_error),
            ("shareBrowserContext", share_browser_context),
            ("reusePage", reuse_page),
        ):
            if value is not None:
                batch_config[key] = value
        for target, values in target_overrides.items():
            existing = batch_config.get(target)
            # Script/batch-config keys win over CLI defaults (matching the
            # single-script path in _merge_cli_target_overrides).
            batch_config[target] = (
                {**values, **existing} if isinstance(existing, dict) else dict(values)
            )
        return batch_config

    def _run_batch_config(batch_config: dict, script_dir: Path) -> None:
        from midscene.cli.batch_runner import BatchRunner
        from midscene.cli.yaml_batch_executor import parse_batch_config

        batch_config = parse_batch_config(batch_config)
        file_paths = [
            str((script_dir / f).resolve()) if not Path(f).is_absolute() else f
            for f in batch_config["files"]
        ]
        batch_config["files"] = file_paths
        missing = [f for f in file_paths if not Path(f).exists()]
        if missing:
            for item in missing:
                console.print(f"[red]Script not found: {item}[/red]")
            raise typer.Exit(1)

        async def _run_batch():

            shared_page_holder: dict = {}

            async def factory(content: str, file_path: str):
                script = parse_yaml_script(content)
                created = await _create_agent_for_script(
                    script,
                    headed,
                    device_id,
                    shared_page=shared_page_holder.get("page"),
                )
                if isinstance(created, tuple):
                    page, options = created
                    if batch_config["share_browser_context"]:
                        shared_page_holder["page"] = page
                    agent = Agent(page, options)
                else:
                    agent = created
                player = ScriptPlayer(script, agent)
                player.shared_page = shared_page_holder.get("page")
                return player

            runner = BatchRunner(batch_config, factory)
            results = await runner.run()
            return runner, results

        runner, results = asyncio.run(_run_batch())
        print_batch_results(console, results, runner)
        if runner.get_failed_files() or runner.get_not_executed_files():
            raise typer.Exit(1)
        console.print("[green]Batch executed successfully[/green]")

    # Batch entry: --config, --files, a directory, or a file with "files"
    if config_file or files:
        if config_file:
            batch_config = _read_batch_config(config_file)
            script_dir = Path(config_file).parent
        else:
            batch_config = {"files": list(files)}
            script_dir = Path.cwd()
        _run_batch_config(_apply_batch_flags(batch_config), script_dir)
        if keep_window:
            _keep_window(console)
        return

    if not script_path:
        console.print("[red]No script path, files, or config provided[/red]")
        raise typer.Exit(1)

    path = Path(script_path)
    if not path.exists():
        console.print(f"[red]Script not found: {script_path}[/red]")
        raise typer.Exit(1)

    if path.is_dir() or _is_batch_config(path):
        if path.is_dir():
            config_path = path / "midscene.yml"
            if not config_path.exists():
                console.print(f"[red]No midscene.yml in directory: {path}[/red]")
                raise typer.Exit(1)
            batch_config = _read_batch_config(str(config_path))
            script_dir = path
        else:
            batch_config = _read_batch_config(str(path))
            script_dir = path.parent
        _run_batch_config(_apply_batch_flags(batch_config), script_dir)
    else:
        script = _merge_cli_target_overrides(
            parse_yaml_script(path.read_text(encoding="utf-8")), target_overrides
        )

        async def _run():
            created = await _create_agent_for_script(script, headed, device_id)
            page = None
            if isinstance(created, tuple):
                page, options = created
                agent = Agent(page, options)
            else:
                agent = created
            if artifact_dir:
                agent.options.report_artifact_dir = artifact_dir
            player = ScriptPlayer(script, agent)
            try:
                await player.run()
            finally:
                await agent.destroy()
                if page is not None:
                    await page.close()
            return player

        player = asyncio.run(_run())

        print_script_result(console, player)
        # Upstream treats partial failures (continueOnError) as a non-zero exit too.
        if player.status == "error" or player.failed_tasks:
            raise typer.Exit(1)
        console.print("[green]YAML script executed successfully[/green]")

    if keep_window:
        _keep_window(console)


@siwc_app.command("login")
def siwc_login(
    port: Optional[int] = typer.Option(
        None, "--port", help="Local callback server port"
    ),
    client_id: Optional[str] = typer.Option(
        None, "--client-id", help="OAuth client ID"
    ),
):
    """Sign in with your ChatGPT plan (SIWC) and store credentials."""
    if not run_siwc_login(console, port, client_id):
        raise typer.Exit(1)


@siwc_app.command("refresh")
def siwc_refresh():
    """Refresh the stored ChatGPT (SIWC) credentials without signing in again."""
    if not run_siwc_refresh(console):
        raise typer.Exit(1)


@model_app.command("connect")
def model_connect():
    """Run the model connectivity test (text / vision / aiLocate)."""
    if not run_model_connect(console):
        raise typer.Exit(1)


@model_app.command("verify")
def model_verify():
    """Alias of `model connect` (upstream `midscene model verify`)."""
    if not run_model_verify(console):
        raise typer.Exit(1)


@app.command("report-tool")
def report_tool(
    action: str = typer.Option(
        "split", "--action", help="split | to-markdown | merge-html"
    ),
    html_path: Optional[str] = typer.Option(
        None, "--htmlPath", help="Input report HTML path (split / to-markdown)"
    ),
    html_report: Optional[list[str]] = typer.Option(
        None,
        "--htmlReport",
        help="Input report HTML path for merge-html (repeatable)",
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--outputDir", help="Output directory for generated artifacts"
    ),
    output_name: Optional[str] = typer.Option(
        None, "--outputName", help="Merged report name (without .html)"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite an existing merged report"
    ),
):
    """Transform Midscene report artifacts (upstream `midscene report-tool`)."""
    if not run_report_tool(
        console,
        action,
        html_path,
        html_report,
        output_dir,
        output_name,
        overwrite,
    ):
        raise typer.Exit(1)


@app.command()
def version():
    """Show version information"""
    import midscene

    try:
        console.print(f"Midscene Python v{midscene.__version__}")
    except Exception as e:
        console.print(f"❌ Error getting version: {e}", style="red")


def main():
    """CLI entry point"""
    app()


if __name__ == "__main__":
    main()
