"""Create a ScriptPlayer-compatible agent from YAML (upstream create-yaml-player.ts)."""

from typing import Optional

from rich.console import Console

from midscene.cli.cli_utils import _resolve_served_url
from midscene.cli.config_factory import _build_agent_options


async def create_agent_for_script(
    script: dict,
    headed: bool,
    device_id: Optional[str],
    shared_page=None,
    console: Optional[Console] = None,
):
    """Build an agent from the script's target section (web, android, ios,
    harmony, or computer)."""

    if console is None:
        console = Console()

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
        from midscene.computer import ComputerAgent
        from midscene.computer.device import ComputerDevice

        computer_section = script["computer"] or {}
        # ComputerDevice only grabs the primary display, so a declared displayId
        # raises instead of being silently dropped.
        device = ComputerDevice(display_id=computer_section.get("displayId"))
        return ComputerAgent(device, _build_agent_options(computer_section))

    web_section = script.get("web") or script.get("browser") or script.get("page") or script.get("target") or {}
    from midscene.web_integration import PlaywrightWebPage

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
