#!/usr/bin/env python3
"""Compare exported runtime symbols between upstream TS modules and Python.

The file-level baseline (``check_upstream_alignment.py``) only proves that a
Python module exists.  This script answers a stricter question: for each
aligned module, which *runtime* exports from the upstream TypeScript file are
absent from the mapped Python module?

Classification:

* ``moved``   -- the symbol exists elsewhere under ``midscene/`` (re-export or
                 a different module layout).
* ``missing`` -- the symbol is not defined anywhere in the Python package.

Type-only exports (``interface`` / ``type``), zod schemas (``*Schema``) and
TypeScript enums are counted separately: Python represents those as dicts,
TypedDicts or plain constants, so a name mismatch is not necessarily a gap.

Usage:
    python scripts/check_upstream_api_alignment.py [--json PATH] [--quiet]
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(REPO_ROOT, "scripts", "upstream_alignment_baseline.json")
DEFAULT_UPSTREAM_ROOT = "/home/zhangming/gitspace/midscene"

_EXPORT_DECL = re.compile(
    r"^export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
    r"(function|class|const|let|var|enum|interface|type)\s+([A-Za-z0-9_$]+)",
    re.MULTILINE,
)
_TYPE_EXPORT_LIST = re.compile(r"^export\s+type\s*\{([^}]*)\}", re.MULTILINE)
_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}(\s*from\s*['\"][^'\"]+['\"])?", re.MULTILINE)


def to_snake(name: str) -> str:
    """Convert camelCase/PascalCase/SCREAMING_SNAKE to lower snake_case."""
    if name.isupper():
        return name.lower()
    step = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    step = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step)
    step = re.sub(r"[^A-Za-z0-9]+", "_", step)
    return step.strip("_").lower()


def _exported_names(ts_source: str) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (runtime, schema, type_level) export names from one TS file.

    ``export { ... } from './other'`` is a barrel re-export: the symbol is
    audited in the module that defines it, so barrels are not reported here.
    """
    runtime: Set[str] = set()
    schema: Set[str] = set()
    type_level: Set[str] = set()

    for kind, name in _EXPORT_DECL.findall(ts_source):
        if kind in ("interface", "type"):
            type_level.add(name)
        elif kind == "enum":
            runtime.add(name)
        elif name.endswith("Schema") or name.endswith("schema"):
            schema.add(name)
        else:
            runtime.add(name)

    def _add_names(block: str, dest: Set[str]) -> None:
        for item in block.split(","):
            item = item.strip()
            if not item:
                continue
            if item.startswith("type "):
                type_level.add(item[len("type ") :].strip().split(" as ")[-1].strip())
                continue
            exported = item.split(" as ")[-1].strip()
            if exported.endswith("Schema") or exported.endswith("schema"):
                schema.add(exported)
            else:
                dest.add(exported)

    for block in _TYPE_EXPORT_LIST.findall(ts_source):
        _add_names(block, type_level)

    for block, from_clause in _EXPORT_LIST.findall(ts_source):
        # Local re-exports may name values defined in this file; external
        # barrels point at a module that is audited separately.
        if not from_clause:
            _add_names(block, runtime)

    return runtime, schema, type_level


def _python_symbols(path: str) -> Set[str]:
    """Top-level defs, classes, assignments and ``__all__`` entries."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return set()

    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    names.update(
                        item.id for item in target.elts if isinstance(item, ast.Name)
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                value = []
            names.update(item for item in value if isinstance(item, str))
    return {to_snake(name) for name in names}


def _package_of(upstream_path: str) -> str:
    parts = upstream_path.split("/")
    return parts[0] if parts else "unknown"


def scan(upstream_root: str) -> Dict[str, object]:
    baseline = json.load(open(BASELINE, encoding="utf-8"))

    # Repo-wide symbol index so moved implementations are not reported missing.
    symbols_by_module: Dict[str, Set[str]] = {}
    global_symbols: Set[str] = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "midscene", "**", "*.py"), recursive=True):
        names = _python_symbols(path)
        rel = os.path.relpath(path, REPO_ROOT)
        symbols_by_module[rel] = names
        global_symbols |= names

    modules: List[Dict[str, object]] = []
    totals = Counter()

    for entry in baseline["files"]:
        if entry.get("status") != "aligned":
            continue
        upstream_rel = entry["upstream"]
        ts_path = os.path.join(
            upstream_root, "packages", entry["package"], "src", upstream_rel
        )
        if not os.path.exists(ts_path):
            continue
        source = open(ts_path, encoding="utf-8").read()
        runtime, schema, type_level = _exported_names(source)
        totals["runtime_exports"] += len(runtime)
        totals["schema_exports"] += len(schema)
        totals["type_exports"] += len(type_level)

        py_rel = os.path.join("midscene", entry["python"])
        py_path = os.path.join(REPO_ROOT, py_rel)
        local = _python_symbols(py_path) if os.path.exists(py_path) else set()

        moved: List[Dict[str, str]] = []
        missing: List[str] = []
        for name in sorted(runtime):
            snake = to_snake(name)
            if snake in local:
                continue
            owner = next(
                (
                    module
                    for module, names in symbols_by_module.items()
                    if snake in names and module != py_rel
                ),
                None,
            )
            if owner:
                moved.append({"name": name, "found_in": owner})
            else:
                missing.append(name)

        if not moved and not missing:
            continue
        modules.append(
            {
                "package": entry["package"],
                "upstream": upstream_rel,
                "python": entry["python"],
                "runtime_exports": len(runtime),
                "missing": missing,
                "moved": moved,
            }
        )
        totals["modules_with_gaps"] += 1
        totals["missing"] += len(missing)
        totals["moved"] += len(moved)
        if missing:
            totals["modules_with_missing"] += 1

    modules.sort(key=lambda item: (-len(item["missing"]), item["upstream"]))

    by_package: Dict[str, Counter] = defaultdict(Counter)
    for item in modules:
        pkg = by_package[item["package"]]
        pkg["modules"] += 1
        pkg["missing"] += len(item["missing"])
        pkg["moved"] += len(item["moved"])

    return {
        "upstream_root": upstream_root,
        "counts": dict(totals),
        "by_package": {pkg: dict(counter) for pkg, counter in sorted(by_package.items())},
        "modules": modules,
    }


def _print_report(result: Dict[str, object], limit: int) -> None:
    counts = result["counts"]
    print(
        "API-level gaps: "
        f"{counts.get('modules_with_gaps', 0)} modules, "
        f"{counts.get('missing', 0)} missing runtime exports, "
        f"{counts.get('moved', 0)} moved/re-exported."
    )
    print(
        "Excluded as type-level: "
        f"{counts.get('type_exports', 0)} interfaces/types, "
        f"{counts.get('schema_exports', 0)} zod schemas, enums kept as runtime."
    )
    print()
    print(f"{'pkg':<18}{'modules':>8}{'missing':>9}{'moved':>7}")
    for pkg, row in result["by_package"].items():
        print(
            f"{pkg:<18}{row.get('modules', 0):>8}"
            f"{row.get('missing', 0):>9}{row.get('moved', 0):>7}"
        )

    print()
    print(f"Top {limit} modules by truly missing exports:")
    shown = 0
    for item in result["modules"]:
        if not item["missing"]:
            continue
        shown += 1
        if shown > limit:
            break
        preview = ", ".join(item["missing"][:6])
        suffix = " ..." if len(item["missing"]) > 6 else ""
        print(
            f"  {len(item['missing']):>3}  {item['package']}/{item['upstream']}"
            f"  ->  {item['python']}\n       {preview}{suffix}"
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=os.environ.get("MIDSCENE_UPSTREAM_ROOT", DEFAULT_UPSTREAM_ROOT),
    )
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv) if argv else None)

    if not os.path.isdir(os.path.join(args.upstream_root, "packages")):
        print(f"upstream repo not found: {args.upstream_root}", file=sys.stderr)
        return 2

    result = scan(args.upstream_root)
    if not args.quiet:
        _print_report(result, args.limit)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
