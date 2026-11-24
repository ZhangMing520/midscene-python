"""Standalone case runner (upstream engine/case-runner.ts)."""

from typing import Any

from midscene.core.test_runner.engine.registry import NodeRegistry
from midscene.core.test_runner.engine.run_collected_case import run_collected_case
from midscene.core.test_runner.node.types import NodeDefinition
from midscene.core.test_runner.parser.normalize import normalize_steps


class CaseRunner:
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        options = options or {}
        self.registry = NodeRegistry(options.get("nodes"))
        self.context = options.get("context")

    def register(self, node: NodeDefinition) -> "CaseRunner":
        self.registry.register(node)
        return self

    async def run(self, case_input: dict[str, Any]) -> dict[str, Any]:
        def resolve_for_normalize(name: str) -> dict[str, Any] | None:
            node = self.registry.get(name)
            if node is None:
                return None
            return {"stringInputKey": node.string_input_key}

        collected_case = {
            "caseId": "standalone-case",
            "projectId": "standalone-project",
            "sourcePath": "",
            "caseIndex": 0,
            "definition": {
                "name": case_input.get("name") or "case",
                "tags": list(case_input.get("tags") or []),
                "steps": normalize_steps(
                    case_input.get("steps"), resolve_for_normalize
                ),
            },
        }
        result = await run_collected_case(
            collected_case,
            {
                "resolveNode": lambda name: self.registry.require(name),
                "context": self.context,
                "createRunId": lambda: "standalone-case",
            },
        )

        fatal_step_error = None
        for step in result.get("steps") or []:
            if step.get("status") != "success" and not step.get("continuedAfterError"):
                fatal_step_error = step.get("error")
                break
        if fatal_step_error is not None:
            raise fatal_step_error
        return result


def create_case_runner(
    options: dict[str, Any] | None = None,
) -> CaseRunner:
    return CaseRunner(options)


__all__ = ["CaseRunner", "create_case_runner"]
