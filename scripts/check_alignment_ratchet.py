#!/usr/bin/env python3
"""Alignment ledger ratchet.

The ledger (``scripts/upstream_alignment_ledger.json``) is the committed
snapshot of every module that still differs from upstream.  This script
recomputes the gaps and fails when the code introduces a *new* gap:

* a module that was clean now has missing exports / functions / classes /
  methods;
* a module marked ``done`` still has gaps;
* a module with gaps is not present in the ledger.

Closing gaps is always allowed.  ``--update`` rewrites the ledger after a
batch; it refuses to write when new gaps appeared unless
``--allow-new-gaps`` is passed (useful right after syncing a new upstream
version).

Usage:
    python scripts/check_alignment_ratchet.py
    python scripts/check_alignment_ratchet.py --update
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
LEDGER = os.path.join(SCRIPT_DIR, "upstream_alignment_ledger.json")
BASELINE = os.path.join(SCRIPT_DIR, "upstream_alignment_baseline.json")
PLAN = os.path.join(REPO_ROOT, "docs", "upstream-alignment-plan.md")
DEFAULT_UPSTREAM_ROOT = "/home/zhangming/gitspace/midscene"

sys.path.insert(0, SCRIPT_DIR)
from check_upstream_api_alignment import scan as scan_api  # noqa: E402
from check_upstream_method_alignment import scan as scan_methods  # noqa: E402

_PHASE_MODULE = re.compile(r"`(core/[^`]+?\.ts)`")


def _phase_map(plan_path: str) -> Dict[str, str]:
    """Read Phase 1 module names from the plan; everything else follows §7.5."""
    if not os.path.exists(plan_path):
        return {}
    text = open(plan_path, encoding="utf-8").read()
    match = re.search(r"^### Phase 1.*?(?=^### Phase 2)", text, re.M | re.S)
    if not match:
        return {}
    return {f"core/{name.split('core/', 1)[-1]}": "P1"
            for name in _PHASE_MODULE.findall(match.group(0))}


def _batch_of(key: str, phase_map: Dict[str, str]) -> str:
    if key in phase_map:
        return phase_map[key]
    package = key.split("/", 1)[0]
    if package == "shared":
        return "P2"
    if package == "core":
        return "P3"
    return "P4"


def _api_entries(upstream_root: str) -> Dict[str, Dict[str, object]]:
    result = scan_api(upstream_root)
    return {
        f"{item['package']}/{item['upstream']}": item
        for item in result["modules"]  # type: ignore[index]
    }


def _method_entries(upstream_root: str) -> Dict[str, Dict[str, object]]:
    result = scan_methods(upstream_root)
    return {
        f"{item['package']}/{item['upstream']}": item
        for item in result["modules"]  # type: ignore[index]
    }


def _method_keys(item: Dict[str, object]) -> Dict[str, Set[str]]:
    return {
        "missing_functions": {
            entry["name"] for entry in item.get("missing_functions", [])  # type: ignore[union-attr]
        },
        "missing_classes": set(item.get("missing_classes", [])),  # type: ignore[arg-type]
        "missing_methods": {
            f"{entry['class']}.{entry['name']}"
            for entry in item.get("missing_methods", [])  # type: ignore[union-attr]
        },
        "signature_mismatch": {
            f"{entry.get('class', '')}.{entry['name']}"
            for entry in item.get("signature_mismatch", [])  # type: ignore[union-attr]
        },
    }


def build_state(upstream_root: str) -> Dict[str, Dict[str, object]]:
    phase_map = _phase_map(PLAN)
    api = _api_entries(upstream_root)
    method = _method_entries(upstream_root)
    baseline = json.load(open(BASELINE, encoding="utf-8"))
    state: Dict[str, Dict[str, object]] = {}

    for entry in baseline["files"]:
        if entry.get("status") != "aligned":
            continue
        key = f"{entry['package']}/{entry['upstream']}"
        api_item = api.get(key, {})
        method_item = method.get(key, {})
        api_missing = list(api_item.get("missing", []))  # type: ignore[arg-type]
        api_moved = list(api_item.get("moved", []))  # type: ignore[arg-type]
        method_keys = _method_keys(method_item)
        has_gaps = bool(
            api_missing
            or method_keys["missing_functions"]
            or method_keys["missing_classes"]
            or method_keys["missing_methods"]
        )
        state[key] = {
            "module": key,
            "python": entry["python"],
            "package": entry["package"],
            "batch": _batch_of(key, phase_map),
            "status": "partial" if has_gaps else "done",
            "api_missing": api_missing,
            "api_moved": api_moved,
            "method_missing_functions": sorted(method_keys["missing_functions"]),
            "method_missing_classes": sorted(method_keys["missing_classes"]),
            "method_missing_methods": sorted(method_keys["missing_methods"]),
            "signature_mismatch": sorted(method_keys["signature_mismatch"]),
        }
    return state


def load_ledger() -> Dict[str, Dict[str, object]]:
    if not os.path.exists(LEDGER):
        return {}
    with open(LEDGER, encoding="utf-8") as handle:
        data = json.load(handle)
    return {item["module"]: item for item in data.get("modules", [])}


def _new_items(current: Iterable[str], previous: Iterable[str]) -> List[str]:
    return sorted(set(current) - set(previous))


def compare(
    current: Dict[str, Dict[str, object]],
    previous: Dict[str, Dict[str, object]],
) -> List[str]:
    violations: List[str] = []
    if not previous:
        return ["ledger is empty; run --update to create the initial snapshot"]

    for key, item in current.items():
        old = previous.get(key)
        if old is None:
            if item["status"] != "done":
                violations.append(f"{key}: module with gaps is not in the ledger")
            continue
        for field in ("api_missing", "method_missing_functions",
                      "method_missing_classes", "method_missing_methods"):
            added = _new_items(item[field], old.get(field, []))  # type: ignore[arg-type]
            if added:
                violations.append(f"{key}: new {field}: {', '.join(added)}")
        if old.get("status") == "done" and item["status"] != "done":
            violations.append(f"{key}: status regressed from done to partial")

    return violations


def write_ledger(
    current: Dict[str, Dict[str, object]],
    previous: Dict[str, Dict[str, object]],
    upstream_root: str,
) -> None:
    modules: List[Dict[str, object]] = []
    for key, item in sorted(current.items()):
        old = previous.get(key, {})
        merged = dict(item)
        merged["notes"] = old.get("notes", "")
        merged["owner"] = old.get("owner", "")
        modules.append(merged)

    totals = Counter()
    for item in modules:
        totals["modules"] += 1
        totals["api_missing"] += len(item["api_missing"])  # type: ignore[arg-type]
        totals["method_missing_functions"] += len(item["method_missing_functions"])  # type: ignore[arg-type]
        totals["method_missing_classes"] += len(item["method_missing_classes"])  # type: ignore[arg-type]
        totals["method_missing_methods"] += len(item["method_missing_methods"])  # type: ignore[arg-type]
        totals["signature_mismatch"] += len(item["signature_mismatch"])  # type: ignore[arg-type]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "upstream_root": upstream_root,
        "counts": dict(totals),
        "modules": modules,
    }
    with open(LEDGER, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _summary(current: Dict[str, Dict[str, object]]) -> str:
    totals = Counter()
    for item in current.values():
        totals["modules"] += 1
        if item["status"] == "done":
            totals["done"] += 1
            continue
        totals["partial"] += 1
        totals["api_missing"] += len(item["api_missing"])  # type: ignore[arg-type]
        totals["method_missing"] += (
            len(item["method_missing_functions"])  # type: ignore[arg-type]
            + len(item["method_missing_classes"])  # type: ignore[arg-type]
            + len(item["method_missing_methods"])  # type: ignore[arg-type]
        )
    return (
        f"modules={totals['modules']} done={totals['done']} "
        f"partial={totals['partial']} api_missing={totals['api_missing']} "
        f"method_missing={totals['method_missing']}"
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=os.environ.get("MIDSCENE_UPSTREAM_ROOT", DEFAULT_UPSTREAM_ROOT),
    )
    parser.add_argument("--update", action="store_true",
                        help="rewrite the ledger with the current gaps")
    parser.add_argument("--allow-new-gaps", action="store_true",
                        help="with --update, accept newly introduced gaps")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv) if argv else None)

    if not os.path.isdir(os.path.join(args.upstream_root, "packages")):
        print(f"upstream repo not found: {args.upstream_root}", file=sys.stderr)
        return 2

    current = build_state(args.upstream_root)
    previous = load_ledger()
    violations = compare(current, previous)

    if violations and not args.quiet:
        print("New alignment gaps detected:")
        for violation in violations:
            print(f"  - {violation}")

    if args.update:
        if violations and previous and not args.allow_new_gaps:
            print("\nrefusing to update the ledger; close the gaps first "
                  "or pass --allow-new-gaps", file=sys.stderr)
            return 1
        write_ledger(current, previous, args.upstream_root)
        print(f"\nupdated {os.path.relpath(LEDGER, REPO_ROOT)} :: {_summary(current)}")
        return 0

    if violations:
        print(f"\nFAILED: {len(violations)} ratchet violation(s); "
              f"current {_summary(current)}")
        return 1
    print(f"OK: no new gaps :: {_summary(current)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
