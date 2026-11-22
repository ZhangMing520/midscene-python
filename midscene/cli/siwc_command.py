"""SIWC sign-in commands (upstream packages/cli/src/siwc-command.ts)."""

import asyncio
import inspect
import math
import re
import time
import uuid
import webbrowser
from typing import Any, Callable, Dict, Optional

from rich.console import Console

from midscene.cli.dotenv_loader import _load_dotenv
from midscene.cli.openai.credentials import (
    _save_credentials,
    default_credentials_path,
    lock_credentials,
    read_registration,
    require_credentials,
    save_registration,
)
from midscene.cli.openai.errors import SiwcError, describe_siwc_error
from midscene.cli.openai.login import login_with_openai
from midscene.core.ai_model.service_caller.openai.siwc.refresh import (
    refresh_siwc_credentials,
)

USAGE = """Usage:
  midscene model siwc login [--no-open] [--port <port>]
  midscene model siwc refresh

Sign in with ChatGPT or refresh the saved credentials.
Full credentials are saved to ~/.midscene/siwc.json. Only the access token is printed to stdout.
Midscene does not collect your credentials.

Options (login):
  --no-open           Print the authorization URL without opening a browser
  --port <port>       Loopback callback port (default: an available port)
  --help, -h          Show this help
"""


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _format_expires_at(expires_at_ms: float) -> str:
    import datetime

    moment = datetime.datetime.fromtimestamp(
        expires_at_ms / 1000, tz=datetime.timezone.utc
    ).astimezone()
    return moment.strftime("%d %b %Y, %H:%M:%S %Z")


def _format_remaining(expires_at_ms: float) -> str:
    remaining_minutes = math.ceil((expires_at_ms - time.time() * 1000) / 60_000)
    if remaining_minutes == 60:
        return "in 1 hour"
    return f"in {remaining_minutes} minutes"


async def run_siwc_command(
    args: list,
    io: Optional[Dict[str, Callable[[str], None]]] = None,
    credentials_path: Optional[str] = None,
) -> int:
    """Run `midscene model siwc login|refresh` (upstream runSiwcCommand)."""
    if io is None:
        io = {"stdout": print, "stderr": print}
    credentials_path = credentials_path or default_credentials_path()

    if not args or "--help" in args or "-h" in args:
        io["stdout"](USAGE)
        return 0

    action, options = args[0], list(args[1:])
    if action not in ("login", "refresh"):
        io["stderr"](f"Unknown SIWC command: {action}\n{USAGE}")
        return 1

    port = 0
    no_open = False
    seen = set()
    index = 0
    while index < len(options):
        option = options[index]
        if (
            action != "login"
            or option in seen
            or option not in ("--port", "--no-open")
        ):
            io["stderr"](f"Invalid midscene model siwc arguments.\n{USAGE}")
            return 1
        seen.add(option)
        if option == "--no-open":
            no_open = True
        else:
            index += 1
            value = options[index] if index < len(options) else None
            if not value or not re.fullmatch(r"\d+", value) or int(value) > 65535:
                io["stderr"]("--port must be an integer between 0 and 65535.")
                return 1
            port = int(value)
        index += 1

    try:
        unlock = await lock_credentials(credentials_path)
    except Exception as error:
        io["stderr"](describe_siwc_error(error))
        return 1

    try:
        io["stderr"](f"🔄 Starting OpenAI SIWC {action}...")
        saved = read_registration(credentials_path)

        if action == "refresh":
            credentials = await _maybe_await(
                refresh_siwc_credentials(require_credentials(saved))
            )
        else:
            registration = saved or {
                "ext_agent_host_id": f"urn:uuid:{uuid.uuid4()}"
            }
            # Persist the host ID before authorization, including failed attempts.
            if saved is None:
                save_registration(credentials_path, registration)

            def on_authorization(url: str) -> None:
                io["stderr"](
                    f"\nContinue with ChatGPT:\n{url}\n\n"
                    "Waiting for authorization..."
                )
                if not no_open:
                    try:
                        webbrowser.open(url)
                    except Exception:
                        io["stderr"](
                            "Open the URL above in your browser to continue."
                        )

            result = await _maybe_await(
                login_with_openai(
                    port=port,
                    host_id=registration.get("ext_agent_host_id"),
                    client_id=registration.get("client_id"),
                    on_authorization=on_authorization,
                    no_open=no_open,
                )
            )
            if (
                registration.get("subject")
                and result.get("subject") != registration["subject"]
            ):
                raise SiwcError(
                    "Login identity does not match the saved account."
                )
            credentials = result

        save_registration(credentials_path, credentials)
        io["stderr"]("\n🔑 your Access token:")
        io["stdout"](credentials["access_token"])
        expires_at = credentials.get("expires_at")
        if expires_at:
            io["stderr"](
                f"\nExpires at: {_format_expires_at(expires_at)} "
                f"({_format_remaining(expires_at)})"
            )
        io["stderr"](
            f"\n✅ SIWC {action} succeeded.\n\n"
            "You can use this access token as your model API Key in Midscene "
            "by setting MIDSCENE_MODEL_API_KEY.\n\n"
            "Full credentials are saved locally to:\n"
            f"{credentials_path}\n\n"
            "Midscene does not collect your credentials."
        )
        return 0
    except Exception as error:
        io["stderr"](
            f"OpenAI {action} failed.\n{describe_siwc_error(error)}"
        )
        return 1
    finally:
        await unlock()


def run_siwc_login(
    console: Console,
    port: Optional[int] = None,
    client_id: Optional[str] = None,
) -> bool:
    """Sign in with your ChatGPT plan (SIWC) and store credentials."""
    _load_dotenv()
    try:
        credentials = asyncio.run(
            login_with_openai(console=console, port=port, client_id=client_id)
        )
    except Exception as error:
        console.print(f"[red]{describe_siwc_error(error)}[/red]")
        return False

    _save_credentials(
        {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "credentials": credentials,
        }
    )
    masked = (
        credentials["access_token"][:8]
        + "..."
        + credentials["access_token"][-4:]
    )
    console.print(
        f"[green]Signed in "
        f"({credentials.get('email', credentials.get('subject'))})[/green]"
    )
    console.print(f"Access token: {masked}")
    console.print(
        "Credentials stored in ~/.midscene/siwc.json. "
        "Use MIDSCENE_MODEL_AUTH_MODE=siwc to use your ChatGPT plan."
    )
    return True


def run_siwc_refresh(console: Console) -> bool:
    """Refresh the stored ChatGPT (SIWC) credentials without signing in again."""
    _load_dotenv()
    from midscene.core.siwc import (
        SiwcError as CoreSiwcError,
        _read_credentials,
        _save_credentials,
        refresh_siwc_credentials as core_refresh,
    )

    try:
        record = _read_credentials()
        refreshed = asyncio.run(core_refresh(record["credentials"]))
    except CoreSiwcError as e:
        console.print(f"[red]{e}[/red]")
        return False

    _save_credentials({**record, "credentials": refreshed})
    masked = refreshed["access_token"][:8] + "..." + refreshed["access_token"][-4:]
    console.print("[green]SIWC credentials refreshed[/green]")
    console.print(f"Access token: {masked}")
    return True
