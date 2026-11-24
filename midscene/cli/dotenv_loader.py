"""Load `.env` config from the current directory (upstream dotenv-loader.ts)."""

from collections.abc import Callable
from pathlib import Path

from rich.console import Console


def load_dotenv_config(
    console: Console | None = None,
    override: bool = False,
    debug: bool = False,
    log: Callable[[str], None] | None = None,
) -> None:
    """Load `.env` from the current directory (upstream dotenv-loader).

    Existing environment variables win unless `override` is set."""
    import os

    def emit(message: str) -> None:
        if log is not None:
            log(message)
        elif console is not None:
            console.print(f"[dim]{message}[/dim]")

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
                emit(f".env: {key} kept from environment")
            continue
        os.environ[key] = value
        if debug:
            emit(f".env: {key} loaded")


def _load_dotenv(
    override: bool = False, debug: bool = False, console: Console | None = None
) -> None:
    """Backward-compatible helper that loads `.env` with a default console."""
    load_dotenv_config(console or Console(), override=override, debug=debug)
