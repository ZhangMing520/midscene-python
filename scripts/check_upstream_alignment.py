#!/usr/bin/env python3
"""Check the Python SDK file layout against the upstream TypeScript packages.

The baseline is a one-time, reviewed snapshot of every upstream ``.ts`` file
with one of four statuses:

* ``aligned``  - an equivalent Python file lives at the same relative path.
* ``merged``   - the upstream file's logic lives in a different Python file
                 (for example two upstream files folded into one Python module).
* ``pending``  - can be ported, but is not implemented yet.
* ``exempt``   - Node/browser/platform-only; there is no Python counterpart.

After the baseline is generated, this script only reports *new* upstream files
and *regressions* (an aligned/merged target disappeared). Pending items are
informational, so previous known gaps no longer look like fresh discoveries.

Usage:
    python3 scripts/check_upstream_alignment.py
    python3 scripts/check_upstream_alignment.py --generate
    python3 scripts/check_upstream_alignment.py --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM = REPO_ROOT.parent / "midscene"
PYTHON_ROOT = REPO_ROOT / "midscene"
BASELINE_PATH = Path(__file__).with_name("upstream_alignment_baseline.json")

# upstream package directory (under packages/) -> Python package directory
PACKAGES: Dict[str, str] = {
    "android": "android",
    "core": "core",
    "computer": "computer",
    "computer-linux": "computer_linux",
    "computer-mac": "computer_mac",
    "computer-win": "computer_win",
    "harmony": "harmony",
    "ios": "ios",
    "shared": "shared",
    "webdriver": "webdriver",
    "web-integration": "web_integration",
    "cli": "cli",
}

# CamelCase file names whose snake_case form differs from the generic rule.
NAME_ALIASES = {
    "WebDriverClient": "webdriver_client",
}

# (package, upstream relative path) -> (python path relative to midscene/, note)
MERGED: Dict[Tuple[str, str], Tuple[str, str]] = {}

# (package regex, path regex, reason) - checked after MERGED and aligned.
EXEMPT: List[Tuple[str, str, str]] = [
    (
        "core",
        r"^yaml\.ts$",
        "Python cannot have both yaml.py and the yaml/ package",
    ),
    (
        "core",
        r"^ai-model/service-caller/proxy/proxy-deps\.(node|stub)\.ts$",
        "undici dynamic import; httpx handles proxies directly",
    ),
    (
        "core",
        r"^ai-model/shared/action-schema\.ts$",
        "ZodDefault introspection; Python action schemas have no such concept",
    ),
    (
        "core",
        r"^yaml/execution-context\.(node|stub)\.ts$",
        "Node/browser build variants; Python has yaml/execution_context.py",
    ),
    ("shared", r"^baseDB\.ts$", "browser IndexedDB API"),
    ("shared", r"^recorder\.ts$", "browser recorder runtime"),
    (
        "shared",
        r"^console-context\.(node|stub)\.ts$",
        "Node build variants; Python has shared/console_context.py",
    ),
    ("shared", r"^node/fs\.ts$", "Node filesystem binding"),
    ("shared", r"^polyfills/.*\.ts$", "Node async_hooks polyfill"),
    (
        "shared",
        r"^img/(get-photon|get-sharp|photon-loader)\.ts$",
        "Node image backends; Pillow covers the Python SDK",
    ),
    ("shared", r"^zod-schema-utils\.ts$", "Zod-specific helpers"),
    (
        "shared",
        r"^extractor/(debug|dom-util|locator|web-extractor)\.ts$",
        "browser DOM APIs; Python extracts through Playwright page.evaluate scripts",
    ),
    (
        "shared",
        r"^us-keyboard-layout\.ts$",
        "Puppeteer key table; Python uses Playwright/pyautogui key names",
    ),
    (
        "android",
        r"^(agent-tools|cli|test-runner-nodes)\.ts$",
        "Node CLI / test-runner bindings",
    ),
    (
        "computer",
        r"^(agent-tools|cli|apple-script-keyboard|windows-.*)\.ts$",
        "platform/Node bindings; pyautogui is used cross-platform",
    ),
    (
        "harmony",
        r"^(agent-tools|bin|cli|platform|test-runner-nodes)\.ts$",
        "Node CLI / platform bindings",
    ),
    (
        "ios",
        r"^(agent-tools|bin|cli|platform|test-runner-nodes)\.ts$",
        "Node CLI / platform bindings",
    ),
    (
        "web-integration",
        r"^puppeteer/.*\.ts$",
        "Puppeteer driver is not implemented in the Python SDK",
    ),
    (
        "web-integration",
        r"^cdp-.*\.ts$",
        "CDP proxy is not implemented in the Python SDK",
    ),
    (
        "web-integration",
        r"^chrome-extension/.*\.ts$",
        "browser extension runtime",
    ),
    (
        "web-integration",
        r"^static/.*\.ts$",
        "Playground static page runtime",
    ),
    (
        "web-integration",
        r"^bridge-mode/io-client\.ts$",
        "the Chrome extension is the bridge client; Python only hosts the server",
    ),
    (
        "web-integration",
        r"^(agent-tools.*|bin|cli|cli-options|platform|utils)\.ts$",
        "Node CLI / agent tooling",
    ),
    (
        "web-integration",
        r"^playwright/(agent|ai-fixture|browser-agent|page-agent|report-filename)\.ts$",
        "Playwright test-runner integration; Python users use pytest directly",
    ),
    (
        "web-integration",
        r"^playwright/(reporter|test-runner)/.*\.ts$",
        "Playwright reporter/test-runner; Python users use pytest directly",
    ),
    (
        "web-integration",
        r"^common/test-runner/.*\.ts$",
        "Node test-runner helpers; no Python test-runner runtime",
    ),
    ("cli", r"^framework/.*\.ts$", "rstest (Node) test framework"),
    ("cli", r"^tty-renderer\.ts$", "Rich replaces the Node TTY renderer"),
]

# Known portable work that is simply not done yet.
PENDING: Dict[Tuple[str, str], str] = {
    ("android", "scrcpy-manager.ts"): "needs the scrcpy server binary",
    ("android", "scrcpy-device-adapter.ts"): "needs scrcpy streaming support",
    (
        "computer",
        "xvfb.ts",
    ): "start/stop Xvfb for headless Linux desktop automation",
    (
        "core",
        "ai-model/model-adapter/codex-app-server.ts",
    ): "Codex binary + stdio JSON-RPC",
    (
        "core",
        "ai-model/service-caller/codex/call-codex.ts",
    ): "Codex binary + stdio JSON-RPC",
    (
        "core",
        "ai-model/service-caller/codex/codex-app-server.ts",
    ): "Codex binary + stdio JSON-RPC",
}

def snake(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return name.replace("-", "_").lower()


def python_target(package: str, upstream_rel: str) -> Optional[str]:
    """Map an upstream path to the Python path relative to ``midscene/``."""
    parts = Path(upstream_rel).parts
    filename = parts[-1][:-3]  # strip ".ts"
    if filename.endswith(".d"):
        return None
    if filename in NAME_ALIASES:
        filename = NAME_ALIASES[filename]
    elif filename == "index":
        filename = "__init__"
    else:
        filename = snake(filename)
    directories = [snake(part) for part in parts[:-1]]
    return "/".join([PACKAGES[package], *directories, f"{filename}.py"])


def iter_upstream_files(
    upstream_root: Path,
) -> Iterable[Tuple[str, str]]:
    packages_dir = upstream_root / "packages"
    for package in PACKAGES:
        src = packages_dir / package / "src"
        if not src.is_dir():
            continue
        for dirpath, _, filenames in os.walk(src):
            for filename in sorted(filenames):
                if not filename.endswith(".ts") or filename.endswith(".d.ts"):
                    continue
                full = Path(dirpath) / filename
                yield package, full.relative_to(src).as_posix()


def classify(package: str, rel: str) -> Dict[str, str]:
    key = (package, rel)
    if key in MERGED:
        target, note = MERGED[key]
        return {"status": "merged", "python": target, "reason": note}

    target = python_target(package, rel)
    if target and (PYTHON_ROOT / target).is_file():
        return {"status": "aligned", "python": target}

    for pkg_pattern, path_pattern, reason in EXEMPT:
        if package == pkg_pattern and re.match(path_pattern, rel):
            return {"status": "exempt", "reason": reason}

    if key in PENDING:
        return {"status": "pending", "reason": PENDING[key]}

    return {
        "status": "pending",
        "reason": "not classified yet; decide aligned/merged/exempt or port it",
    }


def generate(upstream_root: Path) -> Dict[str, object]:
    files: List[Dict[str, str]] = []
    for package, rel in iter_upstream_files(upstream_root):
        entry: Dict[str, str] = {"package": package, "upstream": rel}
        entry.update(classify(package, rel))
        files.append(entry)

    counts: Dict[str, int] = {}
    for entry in files:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream_root": str(upstream_root),
        "python_root": str(PYTHON_ROOT),
        "counts": counts,
        "files": files,
    }


def load_baseline(path: Path) -> Dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def check(upstream_root: Path, baseline: Dict[str, object]) -> int:
    files = baseline["files"]
    baseline_keys = {(entry["package"], entry["upstream"]) for entry in files}
    errors: List[str] = []
    pending: List[str] = []

    for entry in files:
        package, rel, status = entry["package"], entry["upstream"], entry["status"]
        upstream_file = upstream_root / "packages" / package / "src" / rel
        if not upstream_file.is_file():
            errors.append(
                f"upstream file is gone: {package}/{rel} (update the baseline)"
            )
            continue
        if status in ("aligned", "merged"):
            target = PYTHON_ROOT / entry["python"]
            if not target.is_file():
                errors.append(
                    f"{status} target missing: {package}/{rel} -> {entry['python']}"
                )
        elif status == "pending":
            pending.append(f"{package}/{rel}: {entry.get('reason', '')}")

    for package, rel in iter_upstream_files(upstream_root):
        if (package, rel) not in baseline_keys:
            errors.append(
                f"new upstream file is not classified: {package}/{rel} "
                "(run --generate and review)"
            )

    counts = baseline.get("counts", {})
    print(
        "baseline: "
        f"{counts.get('aligned', 0)} aligned, "
        f"{counts.get('merged', 0)} merged, "
        f"{counts.get('pending', 0)} pending, "
        f"{counts.get('exempt', 0)} exempt"
    )
    if pending:
        print(f"pending ({len(pending)}):")
        for item in pending:
            print(f"  - {item}")

    if errors:
        print(f"\nERRORS ({len(errors)}):", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("\nOK: no unclassified upstream files and no missing targets.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream",
        type=Path,
        default=DEFAULT_UPSTREAM,
        help=f"upstream midscene repo (default: {DEFAULT_UPSTREAM})",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=f"baseline JSON path (default: {BASELINE_PATH})",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="regenerate the baseline from the current repositories",
    )
    args = parser.parse_args(argv)

    if not (args.upstream / "packages").is_dir():
        print(
            f"upstream repo not found: {args.upstream} "
            "(use --upstream /path/to/midscene)",
            file=sys.stderr,
        )
        return 2

    if args.generate:
        baseline = generate(args.upstream)
        args.baseline.write_text(
            json.dumps(baseline, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        counts = baseline["counts"]
        print(
            f"wrote {args.baseline} "
            f"({len(baseline['files'])} files: "
            f"{counts.get('aligned', 0)} aligned, "
            f"{counts.get('merged', 0)} merged, "
            f"{counts.get('pending', 0)} pending, "
            f"{counts.get('exempt', 0)} exempt)"
        )
        return 0

    if not args.baseline.is_file():
        print(
            f"baseline not found: {args.baseline} (run --generate first)",
            file=sys.stderr,
        )
        return 2

    return check(args.upstream, load_baseline(args.baseline))


if __name__ == "__main__":
    raise SystemExit(main())
