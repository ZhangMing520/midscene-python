"""Shared CLI utilities (upstream packages/cli/src/cli-utils.ts)."""

import glob
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from midscene.cli.config_options import YAML_TARGET_KEYS
from midscene.cli.workflow_format import is_legacy_yaml_path

if TYPE_CHECKING:
    from http.server import ThreadingHTTPServer

_SERVE_SERVERS: dict[str, "ThreadingHTTPServer"] = {}

_STRING_OPTIONS = {"setup", "config", "summary"}
_NUMBER_OPTIONS = {"concurrent", "retry"}
_BOOLEAN_OPTIONS = {
    "headed",
    "keep-window",
    "continue-on-error",
    "share-browser-context",
    "reuse-page",
    "dotenv-override",
    "dotenv-debug",
    "harmony.auto-dismiss-keyboard",
}


def _kebab_to_camel(value: str) -> str:
    parts = value.split("-")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _camel_to_kebab(value: str) -> str:
    result = "".join(f"-{char.lower()}" if char.isupper() else char for char in value)
    return result[1:] if result.startswith("-") else result


def _parse_nested_value(raw: str) -> Any:
    """Coerce a scalar CLI value the way yargs does for unknown options."""
    if raw.isdigit():
        return int(raw)
    try:
        if "." in raw and raw.replace(".", "", 1).isdigit():
            return float(raw)
    except ValueError:
        pass
    return raw


def _assign_nested(options: dict[str, Any], key: str, value: Any) -> None:
    path = [part for part in key.split(".") if part]
    if not path:
        return
    cursor = options
    for part in path[:-1]:
        next_cursor = cursor.get(part)
        if not isinstance(next_cursor, dict):
            next_cursor = {}
            cursor[part] = next_cursor
        cursor = next_cursor
    cursor[path[-1]] = value


def _ensure_both_formats(section: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in section.items():
        camel = _kebab_to_camel(key)
        kebab = _camel_to_kebab(key)
        result[kebab] = value
        result[camel] = value
    return result


async def parse_process_args() -> dict[str, Any]:
    """Parse ``process.argv`` like the upstream yargs CLI (dot-notation on).

    Returns ``{"path": ..., "files": ..., "options": ...}``. Target sections
    expose both kebab-case and camelCase keys, matching upstream's
    ``ensureBothFormats`` pass.
    """
    raw = list(sys.argv[1:])
    options: dict[str, Any] = {"_": []}
    index = 0
    while index < len(raw):
        token = raw[index]
        index += 1
        if not token.startswith("--"):
            options["_"].append(token)
            continue

        key = token[2:]
        if key.startswith("no-") and key[3:] in _BOOLEAN_OPTIONS:
            options[key[3:]] = False
            continue

        if key == "files":
            values: list[str] = []
            while index < len(raw) and not raw[index].startswith("--"):
                values.append(raw[index])
                index += 1
            options["files"] = values
            continue

        has_value = index < len(raw) and not raw[index].startswith("--")
        if key in _BOOLEAN_OPTIONS and not has_value:
            options[key] = True
            continue
        if not has_value:
            options[key] = True
            continue

        value: Any = raw[index]
        index += 1
        if "." in key:
            _assign_nested(options, key, _parse_nested_value(value))
        elif key in _NUMBER_OPTIONS:
            options[key] = int(value) if value.isdigit() else float(value)
        elif key in _BOOLEAN_OPTIONS:
            options[key] = value
        elif key in _STRING_OPTIONS:
            options[key] = value
        else:
            options[key] = _parse_nested_value(value)

    for target in YAML_TARGET_KEYS:
        section = options.get(target)
        if isinstance(section, dict):
            options[target] = _ensure_both_formats(section)

    return {
        "path": options["_"][0] if options["_"] else None,
        "files": options.get("files"),
        "options": options,
    }


def match_yaml_files(
    file_glob: str, options: dict[str, Any] | None = None
) -> list[str]:
    """Expand a YAML glob (upstream matchYamlFiles): directories expand to
    ``**/*.yml``/``**/*.yaml``, results are absolute and sorted."""
    base = Path((options or {}).get("cwd") or os.getcwd())
    candidate = Path(file_glob)
    if not candidate.is_absolute():
        candidate = base / candidate

    if candidate.is_dir():
        patterns = [candidate / "**" / "*.yml", candidate / "**" / "*.yaml"]
    else:
        patterns = [candidate]

    matches = []
    for pattern in patterns:
        matches.extend(glob.glob(str(pattern), recursive=True))

    return sorted(
        {
            os.path.abspath(match)
            for match in matches
            if os.path.isfile(match)
            and match.endswith((".yml", ".yaml"))
            and "node_modules" not in Path(match).parts
        }
    )


def _read_batch_config(path: str) -> dict[str, Any]:
    """Read a batch config as raw camelCase YAML before normalization."""
    import yaml as _yaml

    obj = _yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(obj, dict):
        raise ValueError(f"batch config {path} must be a mapping")
    return obj


def _is_batch_config(path: Path) -> bool:
    """True when the YAML file declares a "files" key (batch config)."""
    if not is_legacy_yaml_path(str(path)):
        return False
    try:
        import yaml as _yaml

        obj = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return isinstance(obj, dict) and "files" in obj
    except Exception:
        return False


def _start_static_server(directory: str) -> "ThreadingHTTPServer":
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


def _keep_window(console: Console | None = None) -> None:
    """Hang like upstream --keep-window; useful for debugging."""
    import time as time_module

    console = console or Console()
    console.print("[dim]browser is still running, use ctrl+c to stop it[/dim]")
    while True:
        time_module.sleep(5)
