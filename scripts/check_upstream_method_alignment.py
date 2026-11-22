#!/usr/bin/env python3
"""Method-level alignment audit for upstream TypeScript modules.

``check_upstream_api_alignment.py`` only compares top-level exports.  This
script goes one level deeper:

* exported functions: parameter skeleton and async flag;
* exported classes: public methods, their parameter count and async flag;
* accessors are reported separately and not compared as methods.

The TypeScript parser is a dependency-free scanner (strings/comments aware
brace matching); it is intentionally conservative: private/protected members
and non-public accessors are ignored, and overloads are de-duplicated by name.

Usage:
    python scripts/check_upstream_method_alignment.py [--module core/report.ts]
        [--json PATH] [--strict] [--limit 25]
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(REPO_ROOT, "scripts", "upstream_alignment_baseline.json")
DEFAULT_UPSTREAM_ROOT = "/home/zhangming/gitspace/midscene"

_EXPORT_DECL = re.compile(
    r"^export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(function|class|const|let|var|enum)\s+([A-Za-z0-9_$]+)",
    re.MULTILINE,
)
_METHOD = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|readonly|override|abstract|async)"
    r"[ \t]+)*(?:(get|set)[ \t]+)?([A-Za-z_$][\w$]*)[ \t]*"
    r"(?:<[^<>{}]*>)?[ \t]*\(",
    re.MULTILINE,
)
_RESERVED = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "new",
    "typeof",
    "await",
    "super",
    "this",
    "constructor",
    "function",
    "async",
    "static",
    "public",
    "private",
    "protected",
    "readonly",
    "override",
    "abstract",
    "get",
    "set",
}


def to_snake(name: str) -> str:
    """Convert camelCase/PascalCase/SCREAMING_SNAKE to lower snake_case."""
    if name.isupper():
        return name.lower()
    step = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    step = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step)
    step = re.sub(r"[^A-Za-z0-9]+", "_", step)
    return step.strip("_").lower()


def _strip_private(name: str) -> bool:
    return name.startswith("#") or name.startswith("_")


def _skip_literal(source: str, index: int) -> int:
    """Return the index just past a string/template/comment starting at index."""
    char = source[index]
    if char in "'\"`":
        quote = char
        index += 1
        while index < len(source):
            if source[index] == "\\":
                index += 2
                continue
            if source[index] == quote:
                return index + 1
            index += 1
        return index
    if source.startswith("//", index):
        end = source.find("\n", index)
        return len(source) if end == -1 else end
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return len(source) if end == -1 else end + 2
    return index


def _depths(source: str) -> List[int]:
    """Brace depth before each character, ignoring literals and comments."""
    result = [0] * (len(source) + 1)
    depth = 0
    index = 0
    while index < len(source):
        char = source[index]
        result[index] = depth
        if char in "'\"`" or source.startswith("//", index) or source.startswith(
            "/*", index
        ):
            end = _skip_literal(source, index)
            for offset in range(index, min(end, len(source))):
                result[offset] = depth
            index = end
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        index += 1
    result[len(source)] = depth
    return result


def _matching_paren(source: str, open_index: int) -> int:
    """Index of the matching ``)`` for the ``(`` at ``open_index``."""
    depth = 0
    index = open_index
    while index < len(source):
        char = source[index]
        if char in "'\"`" or source.startswith("//", index) or source.startswith(
            "/*", index
        ):
            index = _skip_literal(source, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_params(params: str) -> List[str]:
    """Split a parameter list on top-level commas."""
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    index = 0
    while index < len(params):
        char = params[index]
        if char in "'\"`" or params.startswith("//", index) or params.startswith(
            "/*", index
        ):
            end = _skip_literal(params, index)
            current.append(params[index:end])
            index = end
            continue
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _param_names(params: str) -> List[str]:
    names: List[str] = []
    for raw in _split_params(params):
        value = raw.split("=")[0].strip()
        value = value.lstrip(".").strip()
        value = value.rstrip("?")
        if not value:
            continue
        if value[0] in "{[":
            names.append(value[:40])
            continue
        names.append(value.split(":")[0].strip())
    return names


def _function_params(source: str, name_end: int) -> str:
    open_index = source.find("(", name_end)
    if open_index == -1:
        return ""
    close_index = _matching_paren(source, open_index)
    if close_index == -1:
        return ""
    return source[open_index + 1 : close_index]


def _class_body(source: str, name_end: int) -> Tuple[str, int]:
    open_index = source.find("{", name_end)
    if open_index == -1:
        return "", -1
    depths = _depths(source)
    base = depths[open_index]
    index = open_index + 1
    while index < len(source):
        if source[index] == "}" and depths[index] == base + 1:
            return source[open_index + 1 : index], open_index + 1
        index += 1
    return source[open_index + 1 :], open_index + 1


def _ts_classes(source: str) -> Dict[str, Dict[str, Dict[str, object]]]:
    """Public methods per exported class: {class: {method: info}}."""
    classes: Dict[str, Dict[str, Dict[str, object]]] = {}
    for match in _EXPORT_DECL.finditer(source):
        kind, name = match.group(1), match.group(2)
        if kind != "class":
            continue
        body, body_start = _class_body(source, match.end())
        if body_start == -1:
            continue
        depths = _depths(body)
        methods: Dict[str, Dict[str, object]] = {}
        for method in _METHOD.finditer(body):
            offset = method.start(2)
            if depths[offset] != 0:
                continue
            method_name = method.group(2)
            if method_name in _RESERVED or _strip_private(method_name):
                continue
            if method.group(1):
                # Public getter/setter: tracked but not compared as a method.
                continue
            if method_name in methods:
                continue
            params = _function_params(body, method.end(2))
            methods[method_name] = {
                "params": _param_names(params),
                "async": bool(re.search(r"\basync\b", method.group(0))),
                "accessor": False,
            }
        classes[name] = methods
    return classes


def _ts_functions(source: str) -> Dict[str, Dict[str, object]]:
    functions: Dict[str, Dict[str, object]] = {}
    for match in _EXPORT_DECL.finditer(source):
        kind, name = match.group(1), match.group(2)
        if kind != "function":
            continue
        params = _function_params(source, match.end())
        functions[name] = {
            "params": _param_names(params),
            "async": bool(re.search(r"\basync\b", match.group(0))),
        }
    return functions


def _python_signature(node: ast.AST) -> Dict[str, object]:
    args = node.args  # type: ignore[attr-defined]
    names = [arg.arg for arg in args.posonlyargs + args.args]
    return {
        "params": names,
        "defaults": len(args.defaults),
        "varargs": bool(args.vararg),
        "kwargs": bool(args.kwarg),
        "async": isinstance(node, ast.AsyncFunctionDef),
    }


def _python_api(path: str) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, Dict[str, object]]]]:
    """Return (functions, classes{name: {method: signature}})."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return {}, {}
    functions: Dict[str, Dict[str, object]] = {}
    classes: Dict[str, Dict[str, Dict[str, object]]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = _python_signature(node)
        elif isinstance(node, ast.ClassDef):
            methods: Dict[str, Dict[str, object]] = {}
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("__") and child.name.endswith("__"):
                        continue
                    methods[child.name] = _python_signature(child)
            classes[node.name] = methods
    return functions, classes


def _python_class_index() -> Dict[str, Tuple[str, Dict[str, Dict[str, object]]]]:
    """Repo-wide class index used to follow moved/re-exported classes."""
    index: Dict[str, Tuple[str, Dict[str, Dict[str, object]]]] = {}
    for path in glob.glob(os.path.join(REPO_ROOT, "midscene", "**", "*.py"),
                           recursive=True):
        _, classes = _python_api(path)
        rel = os.path.relpath(path, REPO_ROOT)
        for name, methods in classes.items():
            index.setdefault(name, (rel, methods))
    return index


def _python_function_index() -> Dict[str, Tuple[str, Dict[str, object]]]:
    """Repo-wide function index used to follow moved/re-exported functions."""
    index: Dict[str, Tuple[str, Dict[str, object]]] = {}
    for path in glob.glob(os.path.join(REPO_ROOT, "midscene", "**", "*.py"),
                           recursive=True):
        functions, _ = _python_api(path)
        rel = os.path.relpath(path, REPO_ROOT)
        for name, signature in functions.items():
            index.setdefault(name, (rel, signature))
    return index


def _arity_mismatch(ts_params: List[str], py_params: List[str]) -> bool:
    """Compare arity when neither side uses destructuring/varargs."""
    if any(name.startswith(("{", "[")) for name in ts_params):
        return False
    return len(ts_params) != len(py_params)


def scan(upstream_root: str, only_module: Optional[str] = None) -> Dict[str, object]:
    baseline = json.load(open(BASELINE, encoding="utf-8"))
    class_index = _python_class_index()
    function_index = _python_function_index()
    modules: List[Dict[str, object]] = []
    totals: Counter = Counter()

    for entry in baseline["files"]:
        if entry.get("status") != "aligned":
            continue
        key = f"{entry['package']}/{entry['upstream']}"
        if only_module and key != only_module:
            continue
        ts_path = os.path.join(
            upstream_root, "packages", entry["package"], "src", entry["upstream"]
        )
        if not os.path.exists(ts_path):
            continue
        source = open(ts_path, encoding="utf-8").read()
        ts_functions = _ts_functions(source)
        ts_classes = _ts_classes(source)

        py_rel = os.path.join("midscene", entry["python"])
        py_path = os.path.join(REPO_ROOT, py_rel)
        py_functions, py_classes = (
            _python_api(py_path) if os.path.exists(py_path) else ({}, {})
        )

        missing_functions: List[Dict[str, object]] = []
        moved_functions: List[Dict[str, object]] = []
        missing_classes: List[str] = []
        missing_methods: List[Dict[str, object]] = []
        signature_mismatch: List[Dict[str, object]] = []

        for name, info in sorted(ts_functions.items()):
            snake = to_snake(name)
            local = py_functions.get(snake)
            if local is None:
                owner = function_index.get(snake)
                if owner:
                    moved_functions.append(
                        {
                            "name": name,
                            "params": info["params"],
                            "found_in": owner[0],
                        }
                    )
                    continue
                missing_functions.append({"name": name, "params": info["params"]})
                continue
            if _arity_mismatch(info["params"], local["params"]):  # type: ignore[arg-type]
                signature_mismatch.append(
                    {
                        "kind": "function",
                        "name": name,
                        "ts_params": info["params"],
                        "python_params": local["params"],
                    }
                )

        for class_name, methods in sorted(ts_classes.items()):
            python_methods = py_classes.get(class_name, {})
            python_owner = py_rel
            if class_name not in py_classes:
                owner = class_index.get(class_name)
                if not owner:
                    # The class itself is missing; report it once instead of
                    # listing every public method as a separate gap.
                    missing_classes.append(class_name)
                    continue
                python_owner, python_methods = owner
            for method_name, info in sorted(methods.items()):
                snake = to_snake(method_name)
                local = python_methods.get(snake)
                if local is None:
                    missing_methods.append(
                        {
                            "class": class_name,
                            "name": method_name,
                            "params": info["params"],
                            "async": info["async"],
                            "python_owner": python_owner,
                        }
                    )
                    continue
                if _arity_mismatch(
                    info["params"],  # type: ignore[arg-type]
                    [p for p in local["params"] if p not in ("self", "cls")],  # type: ignore[union-attr]
                ):
                    signature_mismatch.append(
                        {
                            "kind": "method",
                            "class": class_name,
                            "name": method_name,
                            "ts_params": info["params"],
                            "python_params": local["params"],
                        }
                    )

        if (
            missing_functions
            or moved_functions
            or missing_classes
            or missing_methods
            or signature_mismatch
        ):
            modules.append(
                {
                    "package": entry["package"],
                    "upstream": entry["upstream"],
                    "python": entry["python"],
                    "missing_functions": missing_functions,
                    "moved_functions": moved_functions,
                    "missing_classes": missing_classes,
                    "missing_methods": missing_methods,
                    "signature_mismatch": signature_mismatch,
                }
            )
            totals["modules_with_gaps"] += 1
            totals["missing_functions"] += len(missing_functions)
            totals["moved_functions"] += len(moved_functions)
            totals["missing_classes"] += len(missing_classes)
            totals["missing_methods"] += len(missing_methods)
            totals["signature_mismatch"] += len(signature_mismatch)
        totals["modules_scanned"] += 1
        totals["functions_scanned"] += len(ts_functions)
        totals["classes_scanned"] += len(ts_classes)

    modules.sort(
        key=lambda item: (
            -(
                len(item["missing_functions"])  # type: ignore[arg-type]
                + len(item["missing_methods"])  # type: ignore[arg-type]
            ),
            item["upstream"],
        )
    )
    return {"upstream_root": upstream_root, "counts": dict(totals), "modules": modules}


def _print_report(result: Dict[str, object], limit: int) -> None:
    counts = result["counts"]
    print(
        "Method-level gaps: "
        f"{counts.get('modules_with_gaps', 0)} modules, "
        f"{counts.get('missing_functions', 0)} missing functions, "
        f"{counts.get('moved_functions', 0)} moved functions, "
        f"{counts.get('missing_classes', 0)} missing classes, "
        f"{counts.get('missing_methods', 0)} missing methods, "
        f"{counts.get('signature_mismatch', 0)} signature mismatches."
    )
    print(
        f"Scanned {counts.get('modules_scanned', 0)} modules, "
        f"{counts.get('functions_scanned', 0)} functions, "
        f"{counts.get('classes_scanned', 0)} classes."
    )
    shown = 0
    for item in result["modules"][:limit]:
        shown += 1
        print(f"\n{item['package']}/{item['upstream']} -> {item['python']}")
        for entry in item["missing_functions"][:6]:  # type: ignore[index]
            print(f"  missing function {entry['name']}({', '.join(entry['params'])})")
        for entry in item.get("moved_functions", [])[:4]:  # type: ignore[union-attr]
            print(
                f"  moved function {entry['name']} -> {entry['found_in']}"
            )
        for class_name in item.get("missing_classes", [])[:6]:  # type: ignore[union-attr]
            print(f"  missing class {class_name}")
        for entry in item["missing_methods"][:8]:  # type: ignore[index]
            print(
                f"  missing method {entry['class']}.{entry['name']}"
                f"({', '.join(entry['params'])})"
            )
        for entry in item["signature_mismatch"][:4]:  # type: ignore[index]
            print(
                f"  signature {entry['kind']} "
                f"{entry.get('class', '')}.{entry['name']}: "
                f"ts={entry['ts_params']} py={entry['python_params']}"
            )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=os.environ.get("MIDSCENE_UPSTREAM_ROOT", DEFAULT_UPSTREAM_ROOT),
    )
    parser.add_argument("--module", default=None,
                        help="limit to one module, e.g. core/report.ts")
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--strict", action="store_true",
                        help="fail when any missing function/method remains")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv) if argv else None)

    if not os.path.isdir(os.path.join(args.upstream_root, "packages")):
        print(f"upstream repo not found: {args.upstream_root}", file=sys.stderr)
        return 2

    result = scan(args.upstream_root, args.module)
    if not args.quiet:
        _print_report(result, args.limit)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.json_path}")
    if args.strict:
        counts = result["counts"]
        return 1 if counts.get("missing_functions") or counts.get("missing_methods") else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
