"""
Midscene CLI - Command line interface for automation scripts

Aligned with upstream @midscene/cli: `midscene run` executes YAML automation
scripts; `midscene model siwc login` performs ChatGPT (SIWC) sign-in;
`midscene model connect` runs the model connectivity test.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import typer
from rich.console import Console

if TYPE_CHECKING:
    from midscene.core.types import AgentOptions


app = typer.Typer(
    name="midscene",
    help="AI-powered automation framework for Web and Android platforms",
    no_args_is_help=True,
)
model_app = typer.Typer(name="model", help="Model configuration and diagnostics")
app.add_typer(model_app, name="model")
siwc_app = typer.Typer(name="siwc", help="Sign-In with ChatGPT (SIWC) auth")
model_app.add_typer(siwc_app, name="siwc")

console = Console()


def _is_batch_config(path: Path) -> bool:
    """True when the YAML file declares a "files" key (batch config)."""
    if path.suffix.lower() not in (".yml", ".yaml"):
        return False
    try:
        import yaml as _yaml

        obj = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return isinstance(obj, dict) and "files" in obj
    except Exception:
        return False


async def _create_agent_for_script(
    script: dict,
    headed: bool,
    device_id: Optional[str],
    shared_page=None,
):
    """Build an agent from the script's target section (web or android)."""

    if script.get("android"):
        from midscene.android import AndroidAgent
        from midscene.android.device import AndroidDevice

        android_section = script["android"] or {}
        target_device_id = device_id or android_section.get("deviceId")
        device = await AndroidDevice.create(target_device_id)
        launch = android_section.get("launch")
        if launch:
            console.print(f"[blue]Launching app: {launch}[/blue]")
            await device.launch_app(launch)
        return AndroidAgent(device, _build_agent_options(android_section))

    web_section = script.get("web") or script.get("browser") or script.get("page") or script.get("target") or {}
    from midscene.web import PlaywrightWebPage

    url = web_section.get("url")
    if not url:
        raise ValueError("web target requires a 'url'")

    chrome_options = {}
    if web_section.get("viewportWidth") and web_section.get("viewportHeight"):
        chrome_options["viewport_size"] = (
            int(web_section["viewportWidth"]),
            int(web_section["viewportHeight"]),
        )
    if web_section.get("userAgent"):
        chrome_options["user_agent"] = web_section["userAgent"]
    if web_section.get("chromeArgs"):
        chrome_options["args"] = [str(arg) for arg in web_section["chromeArgs"]]

    async def _create():
        headless = not headed and bool(web_section.get("headless", True))
        page = await PlaywrightWebPage.create(
            headless=headless,
            **chrome_options,
        )
        await page.navigate_to(url)
        return page

    if shared_page is not None:
        await shared_page.navigate_to(url)
        return shared_page, _build_agent_options(web_section)
    page = await _create()
    return page, _build_agent_options(web_section)


def _build_agent_options(section: dict) -> "AgentOptions":
    from midscene.core.types import AgentOptions

    agent_section = section.get("agent") or {}
    return AgentOptions(
        group_name=agent_section.get("groupName", "Midscene Report"),
        group_description=agent_section.get("groupDescription", ""),
        generate_report=agent_section.get("generateReport", True),
        auto_print_report_msg=agent_section.get("autoPrintReportMsg", True),
        report_file_name=agent_section.get("reportFileName"),
        cache_id=_extract_cache_id(agent_section.get("cache")),
        replanning_cycle_limit=agent_section.get("replanningCycleLimit"),
    )


def _extract_cache_id(cache: object) -> Optional[str]:
    if isinstance(cache, str):
        return cache
    if isinstance(cache, dict):
        return cache.get("id")
    return None


@app.command()
def run(
    script_path: str = typer.Argument(..., help="Path to YAML script file"),
    headed: bool = typer.Option(False, "--headed", help="Run browser in headed mode"),
    device_id: Optional[str] = typer.Option(None, "--device", "-d", help="Android device ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Run a YAML script, a directory of scripts, or a batch config
(upstream `midscene run`)."""
    from midscene.core.agent import Agent
    from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

    if verbose:
        from midscene.shared.logger import setup_logger

        setup_logger(level="DEBUG")

    path = Path(script_path)
    if not path.exists():
        console.print(f"[red]Script not found: {script_path}[/red]")
        raise typer.Exit(1)

    # Batch entry: a directory or a config file with a "files" key
    if path.is_dir() or _is_batch_config(path):
        from midscene.core.batch_runner import BatchRunner, load_batch_config

        if path.is_dir():
            config_file = path / "midscene.yml"
            if not config_file.exists():
                console.print(f"[red]No midscene.yml in directory: {path}[/red]")
                raise typer.Exit(1)
            batch_config = load_batch_config(str(config_file))
            script_dir = path
        else:
            batch_config = load_batch_config(str(path))
            script_dir = path.parent
        file_paths = [
            str((script_dir / f).resolve()) if not Path(f).is_absolute() else f
            for f in batch_config["files"]
        ]
        batch_config["files"] = file_paths

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
        for result in results:
            status = "[green]PASS[/green]" if result["success"] else "[red]FAIL[/red]"
            extra = f" ({result.get('resultType')})" if not result["executed"] else ""
            console.print(f"{status} {result['file']}{extra}")
        if runner.get_failed_files() or runner.get_not_executed_files():
            raise typer.Exit(1)
        console.print("[green]Batch executed successfully[/green]")
        return

    content = path.read_text(encoding="utf-8")
    script = parse_yaml_script(content)

    async def _run():
        created = await _create_agent_for_script(script, headed, device_id)
        page = None
        if isinstance(created, tuple):
            page, options = created
            agent = Agent(page, options)
        else:
            agent = created
        player = ScriptPlayer(script, agent)
        try:
            await player.run()
        finally:
            await agent.destroy()
            if page is not None:
                await page.close()
        return player

    player = asyncio.run(_run())

    if player.output_path:
        console.print(f"[green]Output written to: {player.output_path}[/green]")
    for task in player.failed_tasks:
        console.print(f"[red]task - {task['name']}: {task['error']}[/red]")
    # Upstream treats partial failures (continueOnError) as a non-zero exit too.
    if player.status == "error" or player.failed_tasks:
        raise typer.Exit(1)
    console.print("[green]YAML script executed successfully[/green]")


@siwc_app.command("login")
def siwc_login(
    port: Optional[int] = typer.Option(None, "--port", help="Local callback server port"),
    client_id: Optional[str] = typer.Option(None, "--client-id", help="OAuth client ID"),
):
    """Sign in with your ChatGPT plan (SIWC) and store credentials."""
    import threading
    import time as time_module
    import uuid
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from midscene.core.ai_model.siwc import (
        create_siwc_authorization,
        exchange_siwc_code,
        parse_siwc_callback,
        _save_credentials,
    )

    host_id = f"urn:uuid:{uuid.uuid4()}"
    captured: dict = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = None
            try:
                parsed = parse_siwc_callback(
                    f"http://127.0.0.1{self.path}", captured.get("attempt", {})
                )
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode())
                captured["error"] = e
                return
            if not parsed:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid login state.")
                return
            captured["callback"] = parsed
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><title>Authorization received</title>"
                b"<h1>&#10003; Authorization received</h1>"
                b"<p>You can close this tab. Check your terminal.</p>"
            )

        def log_message(self, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", port or 0), CallbackHandler)
    actual_port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{actual_port}/auth/callback"

    auth = create_siwc_authorization(host_id, redirect_uri, client_id)
    captured["attempt"] = auth["attempt"]

    console.print("[blue]Opening the authorization URL...[/blue]")
    console.print(auth["url"])
    webbrowser.open(auth["url"])

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    timeout = 5 * 60
    start = time_module.time()
    while "callback" not in captured and "error" not in captured:
        if time_module.time() - start > timeout:
            console.print("[red]Authorization timed out.[/red]")
            raise typer.Exit(1)
        time_module.sleep(0.2)
    server.shutdown()

    if "error" in captured:
        console.print(f"[red]{captured['error']}[/red]")
        raise typer.Exit(1)

    async def _exchange():
        return await exchange_siwc_code(
            captured["attempt"], captured["callback"]
        )

    credentials = asyncio.run(_exchange())
    _save_credentials(
        {
            "created_at": time_module.strftime("%Y-%m-%dT%H:%M:%SZ", time_module.gmtime()),
            "credentials": credentials,
        }
    )
    masked = credentials["access_token"][:8] + "..." + credentials["access_token"][-4:]
    console.print(f"[green]Signed in ({credentials.get('email', credentials['subject'])})[/green]")
    console.print(f"Access token: {masked}")
    console.print(
        "Credentials stored in ~/.midscene/siwc.json. "
        'Use MIDSCENE_MODEL_AUTH_MODE=siwc to use your ChatGPT plan.'
    )


@model_app.command("connect")
def model_connect():
    """Run the model connectivity test (text / vision / aiLocate)."""
    from midscene.core.ai_model.connectivity import run_connectivity_test
    from midscene.core.ai_model.env_config import ModelConfigManager

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
    else:
        console.print(f"[red]{result.get('message', '')}[/red]")
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
