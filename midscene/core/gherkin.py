"""Gherkin scenario runner.

Synced from upstream packages/core/src/agent/run-gherkin-scenario.ts (v1.17.4):
Given/When steps run through aiAct (as explicit-setup / user-action prompts),
Then steps run through aiAssert. And/But inherit the previous primary keyword.
"""

import re
from typing import Any, Dict, List, Optional

STEP_KEYWORD_PATTERN = re.compile(r"^(Given|When|Then|And|But)\s+(.+)$", re.IGNORECASE)
HEADER_PATTERN = re.compile(r"^(Scenario):\s*(.*)$", re.IGNORECASE)
UNSUPPORTED_HEADER_PATTERN = re.compile(
    r"^(Feature|Background|Scenario Outline|Scenario Template|Examples|Rule):", re.IGNORECASE
)


def _normalize_step_keyword(keyword: str) -> str:
    lower = keyword.lower()
    for name in ("Given", "When", "Then", "And", "But"):
        if lower == name.lower():
            return name
    return "But"


_PRIMARY_KEYWORDS = ("Given", "When", "Then")


def parse_gherkin_scenario(scenario_text: str) -> Dict[str, Any]:
    """Parse a single-scenario Gherkin text (upstream parseGherkinScenario)."""
    steps: List[Dict[str, Any]] = []
    scenario: Optional[str] = None
    scenario_count = 0
    section = "prelude"

    for line_number, raw_line in enumerate(scenario_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        if line in ('"""', "'''"):
            raise ValueError(
                "runGherkinScenario does not support doc strings; found one at "
                f"line {line_number}."
            )
        if line.startswith("|"):
            raise ValueError(
                "runGherkinScenario does not support data tables; found one at "
                f"line {line_number}."
            )
        if UNSUPPORTED_HEADER_PATTERN.match(line):
            raise ValueError(
                f'runGherkinScenario does not support "{line}" at line {line_number}.'
            )

        header_match = HEADER_PATTERN.match(line)
        if header_match:
            scenario_count += 1
            scenario = header_match.group(2).strip() or None
            section = "scenario"
            continue

        step_match = STEP_KEYWORD_PATTERN.match(line)
        if step_match:
            steps.append(
                {
                    "keyword": _normalize_step_keyword(step_match.group(1)),
                    "text": step_match.group(2).strip(),
                    "line_number": line_number,
                }
            )
            continue

        raise ValueError(
            f"runGherkinScenario does not support content at line {line_number}: {line}"
        )

    if scenario_count > 1:
        raise ValueError(
            f"runGherkinScenario expects exactly one Scenario, but found {scenario_count}."
        )
    if scenario_count == 0 and not steps:
        raise ValueError("runGherkinScenario requires at least one Gherkin step.")

    # resolve And/But to the previous primary keyword
    previous_primary: Optional[str] = None
    for step in steps:
        if step["keyword"] in _PRIMARY_KEYWORDS:
            previous_primary = step["keyword"]
            step["effective_keyword"] = step["keyword"]
        else:
            if previous_primary is None:
                raise ValueError(
                    f'runGherkinScenario cannot resolve "{step["keyword"]}" at line '
                    f'{step["line_number"]}; use Given, When, or Then before '
                    f'{step["keyword"]}.'
                )
            step["effective_keyword"] = previous_primary

    return {"scenario": scenario, "steps": steps}


def build_step_prompt(step: Dict[str, Any]) -> str:
    if step["effective_keyword"] == "Given":
        return f"Set up this precondition: {step['text']}"
    if step["effective_keyword"] == "When":
        return f"Perform this user action: {step['text']}"
    return f"Verify that {step['text']}"


async def run_gherkin_scenario(
    agent: Any,
    scenario_text: str,
    opt: Optional[Dict[str, Any]] = None,
) -> None:
    """Execute the scenario: Given/When -> aiAct, Then -> aiAssert."""
    parsed = parse_gherkin_scenario(scenario_text)
    opt = dict(opt or {})
    opt["cacheable"] = False

    for step in parsed["steps"]:
        if step["effective_keyword"] == "Then":
            await agent.ai_assert(
                step["text"], None, {"context": opt.get("context")}
            )
        else:
            await agent.ai_act(build_step_prompt(step), opt)
