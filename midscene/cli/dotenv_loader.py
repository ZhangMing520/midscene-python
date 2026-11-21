"""Load `.env` config from the current directory (upstream dotenv-loader.ts)."""

from pathlib import Path
from typing import Optional

from rich.console import Console


def load_dotenv_config(
    console: Console, override: bool = False, debug: bool = False
) -> None:
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


def _load_dotenv(
    override: bool = False, debug: bool = False, console: Optional[Console] = None
) -> None:
    """Backward-compatible helper that loads `.env` with a default console."""
    load_dotenv_config(console or Console(), override=override, debug=debug)
