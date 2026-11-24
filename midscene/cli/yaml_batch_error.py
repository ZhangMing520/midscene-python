"""YAML batch execution errors (upstream packages/cli/src/yaml-batch-error.ts)."""

from typing import Any, TypedDict


class YamlBatchErrorOccurrence(TypedDict):
    """One file result attached to a batch execution error."""

    caseId: Any
    result: dict[str, Any]


def _normalize_batch_error(error: Any) -> BaseException:
    if isinstance(error, BaseException):
        return error
    return RuntimeError("Unexpected YAML execution failure")


class YamlBatchExecutionError(Exception):
    """Unexpected YAML execution failure carrying the results collected so far."""

    def __init__(self, error: Any, occurrences: list[YamlBatchErrorOccurrence]) -> None:
        cause = _normalize_batch_error(error)
        super().__init__(str(cause))
        self.__cause__ = cause
        self.name = "YamlBatchExecutionError"
        self.occurrences = [
            {"caseId": occurrence.get("caseId"), "result": occurrence.get("result")}
            for occurrence in occurrences
        ]
        self.results = [occurrence["result"] for occurrence in self.occurrences]


def is_yaml_batch_execution_error(error: Any) -> bool:
    """True when `error` is a YamlBatchExecutionError (upstream type guard)."""
    return isinstance(error, YamlBatchExecutionError)
