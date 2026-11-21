"""SIWC sign-in commands (upstream packages/cli/src/siwc-command.ts)."""

from typing import Optional
import asyncio

from rich.console import Console

from midscene.cli.dotenv_loader import _load_dotenv
from midscene.cli.openai.login import login_with_openai


def run_siwc_login(
    console: Console,
    port: Optional[int] = None,
    client_id: Optional[str] = None,
) -> bool:
    """Sign in with your ChatGPT plan (SIWC) and store credentials."""
    _load_dotenv()
    return login_with_openai(console, port=port, client_id=client_id)


def run_siwc_refresh(console: Console) -> bool:
    """Refresh the stored ChatGPT (SIWC) credentials without signing in again."""
    _load_dotenv()
    from midscene.core.siwc import (
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
        return False

    _save_credentials({**record, "credentials": refreshed})
    masked = refreshed["access_token"][:8] + "..." + refreshed["access_token"][-4:]
    console.print("[green]SIWC credentials refreshed[/green]")
    console.print(f"Access token: {masked}")
    return True
