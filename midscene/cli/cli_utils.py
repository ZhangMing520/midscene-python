"""Shared CLI utilities (upstream packages/cli/src/cli-utils.ts)."""

from pathlib import Path
from typing import Optional

from rich.console import Console

_SERVE_SERVERS: dict = {}


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


def _keep_window(console: Optional[Console] = None) -> None:
    """Hang like upstream --keep-window; useful for debugging."""
    import time as time_module

    console = console or Console()
    console.print("[dim]browser is still running, use ctrl+c to stop it[/dim]")
    while True:
        time_module.sleep(5)
