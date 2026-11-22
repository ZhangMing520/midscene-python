"""Interactive SIWC login flow (upstream packages/cli/src/openai/login.ts)."""

import asyncio
import inspect
import uuid
import webbrowser
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from rich.console import Console

from midscene.cli.openai.errors import SiwcError, with_siwc_stage


def _normalize_options(
    options: Optional[Dict[str, Any]], legacy: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge the upstream-style option mapping with legacy keyword options."""
    merged: Dict[str, Any] = dict(options or {})
    merged.update({key: value for key, value in legacy.items() if value is not None})
    return merged


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if getattr(signal, "aborted", False):
        return True
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return False


_AUTHORIZATION_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorization received · Midscene</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f6f7f9; color: #202124; font-family: system-ui, sans-serif; }
    main { width: 100%; max-width: 480px; padding: 40px 28px; text-align: center; background: white; border: 1px solid #e5e7eb; border-radius: 20px; box-shadow: 0 8px 32px #00000008; }
    h1 { margin: 0 0 20px; font-size: 24px; line-height: 1.4; }
    h1 span { color: #16834a; }
    p { margin: 8px 0 0; color: #596273; font-size: 15px; line-height: 1.6; }
  </style>
</head>
<body>
  <main>
    <h1><span aria-hidden="true">✓</span> Authorization received</h1>
    <p>You can close this tab.</p>
    <p>Check your terminal for the sign-in result and access token.</p>
  </main>
</body>
</html>"""


def _write_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: str,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    payload = body.encode("utf-8")
    writer.write(
        (
            f"HTTP/1.1 {status} { _reason(status) }\r\n"
            f"Content-Type: {content_type}\r\n"
            "Cache-Control: no-store\r\n"
            "Referrer-Policy: no-referrer\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        + payload
    )


def _reason(status: int) -> str:
    return {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        409: "Conflict",
    }.get(status, "OK")


async def _wait_with_signal(future: asyncio.Future, signal: Any) -> Any:
    """Await the callback while honouring an AbortSignal-like object."""
    if signal is None:
        return await future
    while True:
        if _aborted(signal):
            raise SiwcError("OpenAI login cancelled or timed out.")
        done, _ = await asyncio.wait({future}, timeout=0.05)
        if done:
            return future.result()


async def login_with_openai(
    options: Optional[Dict[str, Any]] = None,
    dependencies: Any = None,
    **legacy_options: Any,
) -> Dict[str, Any]:
    """Run the loopback OpenAI (SIWC) login and return verified credentials.

    ``options`` mirrors the upstream ``LoginOptions`` mapping: ``hostId``,
    ``clientId``, ``port``, ``signal`` and ``onAuthorization``. Legacy keyword
    arguments (``console``, ``no_open`` ...) are still accepted for the CLI.
    """
    from midscene.core.ai_model.service_caller.openai.siwc.authorization import (
        create_siwc_authorization,
        exchange_siwc_code,
        parse_siwc_callback,
    )

    opts = _normalize_options(options, legacy_options)
    console: Optional[Console] = opts.get("console")
    streamlit_console = console or Console()

    host_id = opts.get("host_id") or opts.get("hostId")
    if not host_id:
        host_id = f"urn:uuid:{uuid.uuid4()}"
    client_id = opts.get("client_id") or opts.get("clientId")
    port = opts.get("port") or 0
    signal = opts.get("signal")

    if _aborted(signal):
        raise SiwcError("OpenAI login cancelled or timed out.")

    on_authorization = opts.get("on_authorization") or opts.get("onAuthorization")
    no_open = bool(opts.get("no_open") or opts.get("noOpen"))

    if on_authorization is None and console is not None:

        def _default_authorization(url: str) -> None:
            streamlit_console.print("[blue]Opening the authorization URL...[/blue]")
            streamlit_console.print(url)
            if not no_open:
                webbrowser.open(url)

        on_authorization = _default_authorization

    state: Dict[str, Any] = {"attempt": None}
    consumed = {"value": False}
    callback_future: asyncio.Future = asyncio.get_running_loop().create_future()

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            while True:
                header = await reader.readline()
                if not header or header in (b"\r\n", b"\n"):
                    break
            if not request_line:
                _write_response(writer, 404, "Not found")
                return
            parts = request_line.decode("utf-8", errors="replace").split(" ")
            method = parts[0] if parts else ""
            target = parts[1] if len(parts) > 1 else "/"
            url = urlsplit(target)
            if method != "GET" or url.path != "/auth/callback":
                _write_response(writer, 404, "Not found")
                return
            attempt = state["attempt"]
            if attempt is None:
                _write_response(writer, 400, "Authorization has not started.")
                return
            if consumed["value"]:
                _write_response(writer, 409, "Authorization already received.")
                return

            try:
                parsed = parse_siwc_callback(
                    f"{attempt['redirect_uri'].split('/auth/callback')[0]}{target}",
                    attempt,
                )
            except Exception as error:
                _write_response(writer, 400, "Invalid authorization callback.")
                if "error=" in target:
                    consumed["value"] = True
                    if not callback_future.done():
                        callback_future.set_exception(error)
                return
            if not parsed:
                _write_response(
                    writer,
                    400,
                    "Invalid login state. Use the original authorization link.",
                )
                return

            consumed["value"] = True
            _write_response(
                writer,
                200,
                _AUTHORIZATION_HTML,
                "text/html; charset=utf-8",
            )
            if not callback_future.done():
                callback_future.set_result(parsed)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", port)
    try:
        actual_port = server.sockets[0].getsockname()[1]
        redirect_uri = f"http://127.0.0.1:{actual_port}/auth/callback"
        if _aborted(signal):
            raise SiwcError("OpenAI login cancelled or timed out.")

        authorization = create_siwc_authorization(
            host_id,
            redirect_uri,
            client_id,
            "Midscene",
        )
        state["attempt"] = authorization["attempt"]
        if on_authorization is not None:
            await _maybe_await(on_authorization(authorization["url"]))
        if _aborted(signal):
            raise SiwcError("OpenAI login cancelled or timed out.")

        async def await_callback() -> Dict[str, str]:
            return await _wait_with_signal(callback_future, signal)

        callback = await with_siwc_stage(
            "Authorization callback", await_callback
        )
        return await exchange_siwc_code(
            authorization["attempt"], callback
        )
    finally:
        server.close()
        await server.wait_closed()


async def login_with_open_ai(
    options: Optional[Dict[str, Any]] = None,
    dependencies: Any = None,
    **legacy_options: Any,
) -> Dict[str, Any]:
    """Upstream-named alias (loginWithOpenAI -> login_with_open_ai)."""
    return await login_with_openai(options, dependencies, **legacy_options)


__all__ = ["login_with_open_ai", "login_with_openai"]
