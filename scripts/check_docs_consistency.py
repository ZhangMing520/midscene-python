#!/usr/bin/env python3
"""Verify that the alignment docs match the repository state.

The two alignment documents are contracts, not prose:

* ``docs/upstream-alignment-plan.md`` claims specific gap counts per phase.
* ``docs/upstream-deviations.md`` records facts about the Python runtime.

This script re-derives those claims from the repository so the docs cannot
silently drift from the code.  It checks:

1. Required files exist and the docs cross-reference each other.
2. File-level / export-level counts in the plan match the baseline and the
   gap report.
3. Every module with missing exports is assigned to exactly one phase, and
   the per-phase totals match the plan's ``合计`` rows and coverage equation.
4. Modules with only moved/re-exported symbols match the documented list.
5. Facts recorded in the deviations doc still hold in the source code.
6. Removed/stale claims have not crept back in.
7. Markdown tables have a consistent number of columns.

Exit code is 1 when any check fails, so this can run in CI unchanged.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "upstream-alignment-plan.md"
DEVIATIONS = ROOT / "docs" / "upstream-deviations.md"
GAPS = ROOT / "scripts" / "upstream_api_gaps.json"
METHOD_GAPS = ROOT / "scripts" / "upstream_method_gaps.json"
LEDGER = ROOT / "scripts" / "upstream_alignment_ledger.json"
BASELINE = ROOT / "scripts" / "upstream_alignment_baseline.json"

# Paths the plan tells readers to run or inspect.
REQUIRED_FILES = [
    "scripts/check_upstream_alignment.py",
    "scripts/check_upstream_api_alignment.py",
    "scripts/check_upstream_method_alignment.py",
    "scripts/check_alignment_ratchet.py",
    "scripts/upstream_api_gaps.json",
    "scripts/upstream_method_gaps.json",
    "scripts/upstream_alignment_ledger.json",
    "scripts/upstream_alignment_baseline.json",
    "tests/test_report.py",
    "tests/test_report_markdown.py",
    "tests/test_screenshot_store.py",
    "midscene/core/skill/__init__.py",
    "midscene/core/test_runner",
    "midscene/core/test_runner/node/define_node.py",
    "midscene/core/dump/report_artifact_store.py",
]

# Facts asserted by docs/upstream-deviations.md, checked against source files.
FACTS: List[Tuple[str, str, str]] = [
    (
        "planning error cap is 5",
        "midscene/core/agent/common.py",
        "MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP = 5",
    ),
    (
        "waitAfterAction defaults to 300ms",
        "midscene/core/agent/agent_options.py",
        "wait_after_action_ms: int = 300",
    ),
    (
        "action readiness warns after 5000ms",
        "midscene/core/agent/action_readiness.py",
        "5000",
    ),
    (
        "bridge default port is 3766",
        "midscene/web_integration/bridge_mode/common.py",
        "DefaultBridgeServerPort = 3766",
    ),
    (
        "codex app-server spawns a binary",
        "midscene/core/ai_model/service_caller/codex/codex_app_server.py",
        "_spawn_codex_app_server",
    ),
    (
        "codex missing-binary error text",
        "midscene/core/ai_model/service_caller/codex/codex_app_server.py",
        "codex binary not found",
    ),
    (
        "ReportArtifactStore exists",
        "midscene/core/dump/report_artifact_store.py",
        "class ReportArtifactStore",
    ),
]

# Claims that were corrected during the SYNC_TODO migration and must stay out.
STALE_CLAIMS = [
    ("agent-tools is not listed as unported", "agent-tools` / skill CLI"),
    ("test-runner hooks are not listed as unported", "Midscene Test 生命周期"),
    ("codex transport is not listed as unported", "| Codex app-server 传输 |"),
]

PHASE_HEADING = re.compile(r"^### Phase (\d)", re.MULTILINE)
MODULE_PATH = re.compile(
    r"`((?:core|shared|android|cli|computer|harmony|ios|web-integration|webdriver)"
    r"/[^`]+?\.ts)`"
)


class Checker:
    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.passed = 0
        self.failures: List[str] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"PASS {name}" + (f" :: {detail}" if detail else ""))
        else:
            message = name + (f" :: {detail}" if detail else "")
            self.failures.append(message)
            print(f"FAIL {message}")
        return condition

    def section(self, text: str, start: str, end: Optional[str]) -> str:
        try:
            begin = text.index(start)
        except ValueError:
            self.check(f"section exists: {start}", False)
            return ""
        finish = text.index(end, begin + len(start)) if end else len(text)
        return text[begin:finish]

    def summary(self) -> int:
        total = self.passed + len(self.failures)
        if self.failures:
            print(f"\nFAILED: {len(self.failures)}/{total} checks")
            return 1
        print(f"\nOK: {total} checks passed")
        return 0


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def phase_sections(plan: str) -> Dict[int, str]:
    matches = list(PHASE_HEADING.finditer(plan))
    sections: Dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plan)
        sections[int(match.group(1))] = plan[match.start():end]
    return sections


def phase_of(package: str, upstream: str, p1: Iterable[str]) -> int:
    key = f"{package}/{upstream}"
    if key in p1:
        return 1
    if package == "shared" or key == "core/dump/html-utils.ts":
        return 2
    if package == "core":
        return 3
    return 4


def check_tables(checker: Checker, name: str, text: str) -> None:
    bad: List[int] = []
    block: List[Tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith("|"):
            block.append((line_number, line))
            continue
        if block:
            expected = block[0][1].count("|")
            bad.extend(n for n, row in block if row.count("|") != expected)
            block = []
    if block:
        expected = block[0][1].count("|")
        bad.extend(n for n, row in block if row.count("|") != expected)
    checker.check(f"{name}: table columns match", not bad, str(bad[:5]))


def check_counts(
    checker: Checker, plan: str, deviations: str, plan_text: str
) -> None:
    gaps = load_json(GAPS)
    modules = gaps["modules"]  # type: ignore[index]
    missing_modules = [m for m in modules if m["missing"]]
    moved_only = [m for m in modules if m["moved"] and not m["missing"]]
    missing_total = sum(len(m["missing"]) for m in modules)
    moved_total = sum(len(m["moved"]) for m in modules)

    checker.check("gap modules with missing == 120", len(missing_modules) == 120,
                  str(len(missing_modules)))
    checker.check("gap missing symbols == 329", missing_total == 329,
                  str(missing_total))
    checker.check("gap moved symbols == 154", moved_total == 154,
                  str(moved_total))
    checker.check("moved-only modules == 4", len(moved_only) == 4,
                  str(len(moved_only)))

    baseline = load_json(BASELINE)
    status = Counter(item["status"] for item in baseline["files"])  # type: ignore[index]
    file_level = re.search(
        r"(\d+) aligned / (\d+) merged / (\d+) pending / (\d+) exempt", plan
    )
    checker.check("plan states file-level counts", bool(file_level))
    if file_level:
        expected = [int(value) for value in file_level.groups()]
        actual = [
            status.get("aligned", 0),
            status.get("merged", 0),
            status.get("pending", 0),
            status.get("exempt", 0),
        ]
        checker.check("file-level counts match baseline", expected == actual,
                      f"doc={expected} repo={actual}")

    export_level = re.search(
        r"(\d+) 个模块有差异 / (\d+) 个运行时导出缺失 / (\d+) 个已迁移", plan
    )
    checker.check("plan states export-level counts", bool(export_level))
    if export_level:
        module_diffs = len({m["package"] + "/" + m["upstream"] for m in modules
                            if m["missing"] or m["moved"]})
        expected = [int(value) for value in export_level.groups()]
        actual = [module_diffs, missing_total, moved_total]
        checker.check("export-level counts match gap report", expected == actual,
                      f"doc={expected} repo={actual}")

    split = re.search(
        r"其中 (\d+) 个模块存在真正缺失，另外 (\d+) 个模块只有迁移差异", plan
    )
    checker.check("plan states missing/moved-only split", bool(split))
    if split:
        expected = [int(value) for value in split.groups()]
        actual = [len(missing_modules), len(moved_only)]
        checker.check("missing/moved-only split matches", expected == actual,
                      f"doc={expected} repo={actual}")

    test_counts = re.search(
        r"(\d+) 个 Python 文件，其中 (\d+) 个 `test_\*\.py`", plan
    )
    checker.check("plan states test file counts", bool(test_counts))
    if test_counts:
        python_files = list((ROOT / "tests").glob("*.py"))
        test_files = [path for path in python_files if path.name.startswith("test_")]
        expected = [int(value) for value in test_counts.groups()]
        actual = [len(python_files), len(test_files)]
        checker.check("test file counts match", expected == actual,
                      f"doc={expected} repo={actual}")

    method_gaps = load_json(METHOD_GAPS)
    method_counts = method_gaps["counts"]  # type: ignore[index]
    method_row = re.search(
        r"(\d+) 个模块 / (\d+) 个函数 / (\d+) 个类 / (\d+) 个方法缺失", plan
    )
    checker.check("plan states method-level counts", bool(method_row))
    if method_row:
        expected = [int(value) for value in method_row.groups()]
        actual = [
            method_counts.get("modules_with_gaps", 0),
            method_counts.get("missing_functions", 0),
            method_counts.get("missing_classes", 0),
            method_counts.get("missing_methods", 0),
        ]
        checker.check("method-level counts match", expected == actual,
                      f"doc={expected} repo={actual}")

    ledger = load_json(LEDGER)
    ledger_counts = ledger["counts"]  # type: ignore[index]
    aligned_count = status.get("aligned", 0)
    checker.check("ledger has one row per aligned module",
                  len(ledger["modules"]) == aligned_count,  # type: ignore[arg-type]
                  f"ledger={len(ledger['modules'])} aligned={aligned_count}")  # type: ignore[index]
    checker.check("ledger api_missing matches gap report",
                  ledger_counts.get("api_missing") == missing_total,
                  f"ledger={ledger_counts.get('api_missing')} repo={missing_total}")
    checker.check(
        "ledger method totals match method report",
        ledger_counts.get("method_missing_functions")
        == method_counts.get("missing_functions", 0)
        and ledger_counts.get("method_missing_classes")
        == method_counts.get("missing_classes", 0)
        and ledger_counts.get("method_missing_methods")
        == method_counts.get("missing_methods", 0),
    )

    # Phase assignment: parse Phase 1 from the plan, then apply the
    # deterministic rule that the plan documents in section 7.5.
    sections = phase_sections(plan)
    checker.check("plan has Phase 1..4 sections",
                  {1, 2, 3, 4}.issubset(sections), str(sorted(sections)))
    p1 = set(MODULE_PATH.findall(sections.get(1, "")))
    if not p1:
        checker.check("Phase 1 lists modules", False)
        return

    counts = Counter()
    symbols = Counter()
    for module in missing_modules:
        phase = phase_of(module["package"], module["upstream"], p1)
        counts[phase] += 1
        symbols[phase] += len(module["missing"])

    equation = re.search(
        r"模块：(\d+) \(P1\) \+ (\d+) \(P2\) \+ (\d+) \(P3\) \+ (\d+) \(P4\) "
        r"= (\d+)",
        plan,
    )
    checker.check("plan states module coverage equation", bool(equation))
    if equation:
        expected = [int(value) for value in equation.groups()]
        actual = [counts[1], counts[2], counts[3], counts[4],
                  sum(counts.values())]
        checker.check("module coverage equation matches", expected == actual,
                      f"doc={expected} repo={actual}")

    symbol_equation = re.search(
        r"符号：(\d+) \(P1\) \+ (\d+) \(P2\) \+ (\d+) \(P3\) \+ (\d+) \(P4\) "
        r"= (\d+)",
        plan,
    )
    checker.check("plan states symbol coverage equation", bool(symbol_equation))
    if symbol_equation:
        expected = [int(value) for value in symbol_equation.groups()]
        actual = [symbols[1], symbols[2], symbols[3], symbols[4],
                  sum(symbols.values())]
        checker.check("symbol coverage equation matches", expected == actual,
                      f"doc={expected} repo={actual}")

    for phase in (1, 2, 3, 4):
        total = re.search(
            r"\*\*合计\*\*\s*\|\s*\*\*(\d+) 个模块 / (\d+) 个符号\*\*",
            sections.get(phase, ""),
        )
        checker.check(f"Phase {phase} states totals", bool(total))
        if total:
            expected = [int(value) for value in total.groups()]
            actual = [counts[phase], symbols[phase]]
            checker.check(f"Phase {phase} totals match", expected == actual,
                          f"doc={expected} repo={actual}")

    # Moved-only modules must be listed with a re-export batch.
    moved_section = checker.section(plan, "另有 4 个模块", "## 8. 并行执行约定")
    documented_moved = set(MODULE_PATH.findall(moved_section))
    repo_moved = {f"{m['package']}/{m['upstream']}" for m in moved_only}
    checker.check("moved-only modules documented", documented_moved == repo_moved,
                  f"doc-only={sorted(documented_moved - repo_moved)} "
                  f"repo-only={sorted(repo_moved - documented_moved)}")

    checker.check(
        "plan references deviations doc",
        "docs/upstream-deviations.md" in plan_text,
    )
    checker.check(
        "deviations references plan doc",
        "docs/upstream-alignment-plan.md" in deviations,
    )


def check_facts(checker: Checker, deviations: str) -> None:
    for name, relative_path, needle in FACTS:
        path = ROOT / relative_path
        if not path.exists():
            checker.check(f"fact: {name}", False, f"missing {relative_path}")
            continue
        checker.check(f"fact: {name}", needle in read_text(path), relative_path)

    for name, stale in STALE_CLAIMS:
        checker.check(name, stale not in deviations)
    checker.check("Puppeteer remains listed as unported",
                  "Puppeteer 驱动" in deviations)
    checker.check("AiFixture exemption documented",
                  "AiFixture" in deviations and "exempt" in deviations)
    checker.check("bridge port fact documented", "3766" in deviations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="only print failures")
    args = parser.parse_args()
    checker = Checker(verbose=not args.quiet)

    for relative_path in ["docs/upstream-alignment-plan.md",
                          "docs/upstream-deviations.md"]:
        checker.check(f"required file: {relative_path}",
                      (ROOT / relative_path).is_file())
    if not PLAN.is_file() or not DEVIATIONS.is_file() or not GAPS.is_file():
        return checker.summary()

    plan = read_text(PLAN)
    deviations = read_text(DEVIATIONS)

    for relative_path in REQUIRED_FILES:
        checker.check(f"referenced path exists: {relative_path}",
                      (ROOT / relative_path).exists())

    check_counts(checker, plan, deviations, plan)
    check_facts(checker, deviations)
    check_tables(checker, "plan", plan)
    check_tables(checker, "deviations", deviations)
    return checker.summary()


if __name__ == "__main__":
    sys.exit(main())
