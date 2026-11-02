"""
Midscene CLI - Command line interface for automation scripts

Aligned with upstream @midscene/cli: `midscene run` executes YAML automation
scripts; `midscene model siwc login` performs ChatGPT (SIWC) sign-in;
`midscene model connect` runs the model connectivity test.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import typer
from rich.console import Console

if TYPE_CHECKING:
    from midscene.core.types import AgentOptions


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


def _read_batch_config(path: str) -> dict:
    """Read a batch config as raw camelCase YAML before normalization."""
    import yaml as _yaml

    obj = _yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(obj, dict):
        raise ValueError(f"batch config {path} must be a mapping")
    return obj


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


_SERVE_SERVERS: dict = {}


def _start_static_server(directory: str):
    """Serve a local directory for YAML `web.serve` (upstream create-server)."""
    import atexit
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    resolved = str(Path(directory).resolve())
    existing = _SERVE_SERVERS.get(resolved)
    if existing is not None:
        return existing
    handler = functools.partial(SimpleHTTPRequestHandler, directory=resolved)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _SERVE_SERVERS[resolved] = server
    atexit.register(server.shutdown)
    return server


def _resolve_served_url(serve_root: str, url: str) -> str:
    server = _start_static_server(serve_root)
    if not url.startswith("/"):
        return url
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}{url}"


async def _create_agent_for_script(
    script: dict,
    headed: bool,
    device_id: Optional[str],
    shared_page=None,
):
    """Build an agent from the script's target section (web, android, ios,
    harmony, or computer)."""

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

    if script.get("ios"):
        from midscene.ios import IOSAgent, IOSDevice

        ios_section = script["ios"] or {}
        device = IOSDevice(
            host=ios_section.get("wdaHost", "localhost"),
            port=int(ios_section.get("wdaPort", 8100)),
            base_url=ios_section.get("wdaBaseUrl"),
            session_id=ios_section.get("sessionId"),
        )
        await device.connect()
        launch = ios_section.get("launch")
        if launch:
            console.print(f"[blue]Launching app: {launch}[/blue]")
            await device.launch_app(launch)
        return IOSAgent(device, _build_agent_options(ios_section))

    if script.get("harmony"):
        from midscene.harmony import HarmonyAgent, HarmonyDevice

        harmony_section = script["harmony"] or {}
        device = HarmonyDevice(
            device_id=harmony_section.get("deviceId") or device_id or "",
            hdc_path=harmony_section.get("hdcPath"),
        )
        await device.connect()
        launch = harmony_section.get("launch")
        if launch:
            console.print(f"[blue]Launching app: {launch}[/blue]")
            await device.launch_app(launch)
        return HarmonyAgent(device, _build_agent_options(harmony_section))

    if script.get("computer"):
        from midscene.desktop import DesktopAgent
        from midscene.desktop.desktop import DesktopDevice

        computer_section = script["computer"] or {}
        # DesktopDevice only grabs the primary display, so a declared displayId
        # raises instead of being silently dropped.
        device = DesktopDevice(display_id=computer_section.get("displayId"))
        return DesktopAgent(device, _build_agent_options(computer_section))

    web_section = script.get("web") or script.get("browser") or script.get("page") or script.get("target") or {}
    from midscene.web import PlaywrightWebPage

    url = web_section.get("url")
    if not url:
        raise ValueError("web target requires a 'url'")

    serve_root = web_section.get("serve")
    if serve_root:
        url = _resolve_served_url(serve_root, url)

    chrome_options = {}
    if web_section.get("viewportWidth") and web_section.get("viewportHeight"):
        chrome_options["viewport_size"] = (
            int(web_section["viewportWidth"]),
            int(web_section["viewportHeight"]),
        )
    if web_section.get("userAgent"):
        chrome_options["user_agent"] = web_section["userAgent"]
    if web_section.get("deviceScaleFactor") is not None:
        chrome_options["device_scale_factor"] = float(
            web_section["deviceScaleFactor"]
        )
    if web_section.get("acceptInsecureCerts"):
        chrome_options["accept_insecure_certs"] = True
    if web_section.get("cookie"):
        chrome_options["cookie_file"] = str(web_section["cookie"])
    if web_section.get("extraHTTPHeaders"):
        chrome_options["extra_http_headers"] = web_section["extraHTTPHeaders"]
    if web_section.get("chromeArgs"):
        chrome_options["args"] = [str(arg) for arg in web_section["chromeArgs"]]
    if web_section.get("keyboardTypeDelay") is not None:
        chrome_options["keyboard_type_delay"] = float(
            web_section["keyboardTypeDelay"]
        )
    if web_section.get("inputStrategy"):
        chrome_options["input_strategy"] = str(web_section["inputStrategy"])
    if web_section.get("forceSameTabNavigation") is not None:
        chrome_options["force_same_tab_navigation"] = bool(
            web_section["forceSameTabNavigation"]
        )
    if web_section.get("autoFollowNewPage") is not None:
        chrome_options["auto_follow_new_page"] = bool(
            web_section["autoFollowNewPage"]
        )
    if web_section.get("forceChromeSelectRendering") is not None:
        chrome_options["force_chrome_select_rendering"] = bool(
            web_section["forceChromeSelectRendering"]
        )

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


_TARGET_KEYS = (
    "web", "page", "browser", "target",
    "android", "ios", "harmony", "computer", "interface",
)


def _kebab_to_camel(value: str) -> str:
    parts = value.split("-")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _normalize_cli_value(value: str):
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def _parse_cli_target_overrides(raw: list) -> dict:
    """Parse unknown `--web.user-agent x`, `--android.device-id id` options
    (upstream yargs dot-notation). Only known target sections are kept."""
    overrides: dict = {}
    index = 0
    while index < len(raw):
        token = raw[index]
        index += 1
        if not token.startswith("--"):
            continue
        key = token[2:]
        value: object = True
        if index < len(raw) and not raw[index].startswith("--"):
            value = _normalize_cli_value(raw[index])
            index += 1
        target, dot, rest = key.partition(".")
        if not dot or target not in _TARGET_KEYS or not rest:
            continue
        path = [_kebab_to_camel(part) for part in rest.split(".") if part]
        if not path:
            continue
        section = overrides.setdefault(target, {})
        cursor = section
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return overrides


def _merge_cli_target_overrides(script: dict, overrides: dict) -> dict:
    """CLI target options are defaults; keys already in the script win
    (matching the batch runner's merge order)."""
    if not overrides:
        return script
    merged = dict(script)
    for target, values in overrides.items():
        existing = merged.get(target)
        merged[target] = (
            {**values, **existing} if isinstance(existing, dict) else dict(values)
        )
    return merged


def _load_dotenv(override: bool = False, debug: bool = False) -> None:
    """Load `.env` from the current directory (upstream dotenv-loader).

    Existing environment variables win unless `override` is set."""
    import os

    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key in os.environ and not override:
            if debug:
                console.print(f"[dim].env: {key} kept from environment[/dim]")
            continue
        os.environ[key] = value
        if debug:
            console.print(f"[dim].env: {key} loaded[/dim]")


@app.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def run(
    ctx: typer.Context,
    script_path: Optional[str] = typer.Argument(None, help="Path to YAML script file"),
    headed: bool = typer.Option(False, "--headed", help="Run browser in headed mode"),
    device_id: Optional[str] = typer.Option(None, "--device", "-d", help="Android device ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    files: Optional[List[str]] = typer.Option(None, "--files", help="YAML files to run"),
    config_file: Optional[str] = typer.Option(
        None, "--config", help="Batch config YAML path"
    ),
    setup: Optional[str] = typer.Option(
        None, "--setup", help="A YAML file to run before the main files"
    ),
    summary: Optional[str] = typer.Option(
        None, "--summary", help="Path for the summary output file"
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
    from midscene.core.agent import Agent
    from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

    if verbose:
        from midscene.shared.logger import setup_logger

        setup_logger(level="DEBUG")

    _load_dotenv(dotenv_override, dotenv_debug)
    target_overrides = _parse_cli_target_overrides(list(ctx.args))

    def _apply_batch_flags(batch_config: dict) -> dict:
        for key, value in (
            ("setup", setup),
            ("summary", summary),
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
        from midscene.core.batch_runner import BatchRunner, parse_batch_config

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
        for result in results:
            status = "[green]PASS[/green]" if result["success"] else "[red]FAIL[/red]"
            extra = f" ({result.get('resultType')})" if not result["executed"] else ""
            console.print(f"{status} {result['file']}{extra}")
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
            _keep_window()
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

    if keep_window:
        _keep_window()


def _keep_window() -> None:
    """Hang like upstream --keep-window; useful for debugging."""
    import time as time_module

    console.print("[dim]browser is still running, use ctrl+c to stop it[/dim]")
    while True:
        time_module.sleep(5)


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


@siwc_app.command("refresh")
def siwc_refresh():
    """Refresh the stored ChatGPT (SIWC) credentials without signing in again."""
    from midscene.core.ai_model.siwc import (
        SiwcError,
        _read_credentials,
        _save_credentials,
        refresh_siwc_credentials,
    )

    try:
        record = _read_credentials()
        refreshed = asyncio.run(refresh_siwc_credentials(record["credentials"]))
    except SiwcError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _save_credentials({**record, "credentials": refreshed})
    masked = refreshed["access_token"][:8] + "..." + refreshed["access_token"][-4:]
    console.print("[green]SIWC credentials refreshed[/green]")
    console.print(f"Access token: {masked}")


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


@model_app.command("verify")
def model_verify():
    """Alias of `model connect` (upstream `midscene model verify`)."""
    model_connect()


@app.command("report-tool")
def report_tool(
    action: str = typer.Option(
        "split", "--action", help="split | to-markdown | merge-html"
    ),
    html_path: Optional[str] = typer.Option(
        None, "--htmlPath", help="Input report HTML path (split / to-markdown)"
    ),
    html_report: Optional[List[str]] = typer.Option(
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
    from midscene.core.report_viewer import (
        merge_report_files,
        report_file_to_markdown,
        split_report_file,
    )

    if action not in ("split", "to-markdown", "merge-html"):
        console.print(
            f'[red]report-tool: unsupported --action value "{action}". '
            "Currently supported: split, to-markdown, merge-html[/red]"
        )
        raise typer.Exit(1)

    try:
        if action == "merge-html":
            if not html_report:
                console.print(
                    "[red]report-tool: --htmlReport is required for action "
                    '"merge-html".[/red]'
                )
                raise typer.Exit(1)
            result = merge_report_files(
                html_report, output_dir, output_name, overwrite
            )
            console.print(
                f"Merged {len(html_report)} report(s) into "
                f"{result['mergedReportPath']}"
            )
            return

        if not html_path:
            console.print("[red]report-tool: --htmlPath is required[/red]")
            raise typer.Exit(1)
        if not output_dir:
            console.print("[red]report-tool: --outputDir is required[/red]")
            raise typer.Exit(1)

        if action == "to-markdown":
            result = report_file_to_markdown(html_path, output_dir)
            console.print(
                "Markdown export completed. Generated "
                f"{len(result['markdownFiles'])} markdown file(s) and "
                f"{len(result['screenshotFiles'])} screenshot(s). "
                f"Output path: {output_dir}"
            )
            return

        result = split_report_file(html_path, output_dir)
        console.print(
            "Report split completed. Generated "
            f"{len(result['executionJsonFiles'])} execution JSON files and "
            f"{len(result['screenshotFiles'])} screenshots. "
            f"Output path: {output_dir}"
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
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
