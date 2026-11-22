"""Interactive SIWC login flow (upstream packages/cli/src/openai/login.ts)."""

from typing import Any, Callable, Optional
import asyncio
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from rich.console import Console

from midscene.cli.openai.credentials import _save_credentials


def login_with_openai(
    console: Optional[Console] = None,
    port: Optional[int] = None,
    client_id: Optional[str] = None,
    host_id: Optional[str] = None,
    on_authorization: Optional[Callable[[str], None]] = None,
    no_open: bool = False,
    signal: Any = None,
) -> bool:
    """Sign in with your ChatGPT plan (SIWC) and store credentials."""
    from midscene.core.ai_model.service_caller.openai.siwc.authorization import (
        create_siwc_authorization,
        exchange_siwc_code,
        parse_siwc_callback,
    )

    console = console or Console()
    host_id = host_id or f"urn:uuid:{uuid.uuid4()}"
    captured: dict = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
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
    if on_authorization is not None:
        on_authorization(auth["url"])
    if not no_open:
        webbrowser.open(auth["url"])

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    timeout = 5 * 60
    start = time.time()
    while "callback" not in captured and "error" not in captured:
        if time.time() - start > timeout:
            console.print("[red]Authorization timed out.[/red]")
            return False
        time.sleep(0.2)
    server.shutdown()

    if "error" in captured:
        console.print(f"[red]{captured['error']}[/red]")
        return False

    async def _exchange():
        return await exchange_siwc_code(
            captured["attempt"], captured["callback"]
        )

    credentials = asyncio.run(_exchange())
    _save_credentials(
        {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "credentials": credentials,
        }
    )
    masked = credentials["access_token"][:8] + "..." + credentials["access_token"][-4:]
    console.print(
        f"[green]Signed in ({credentials.get('email', credentials['subject'])})[/green]"
    )
    console.print(f"Access token: {masked}")
    console.print(
        "Credentials stored in ~/.midscene/siwc.json. "
        "Use MIDSCENE_MODEL_AUTH_MODE=siwc to use your ChatGPT plan."
    )
    return True


__all__ = ["login_with_openai"]
