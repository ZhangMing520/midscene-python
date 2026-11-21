"""Infrastructure failures around a workflow run (upstream execution-failure.ts)."""

from typing import Any, Iterable, List

from midscene.core.test_runner.errors import WorkflowError


def _error_message(error: Any) -> str:
    message = getattr(error, "message", None)
    if isinstance(message, str):
        return message
    return str(error)


class WorkflowExecutionFailure(WorkflowError):
    """An infrastructure failure still carries all execution facts collected so far."""

    def __init__(self, result: Any, errors: Iterable[Any]) -> None:
        error_list = list(errors)
        super().__init__(
            "; ".join(_error_message(error) for error in error_list),
            {
                "code": "WORKFLOW_EXECUTION_FAILURE",
                "cause": error_list[0] if error_list else None,
            },
        )
        self.result = result
        self.errors: List[Any] = error_list


class WorkflowAggregateError(WorkflowError):
    """Python counterpart of the upstream `AggregateError`."""

    def __init__(self, errors: Iterable[Any], message: str = "Workflow failed") -> None:
        error_list = list(errors)
        super().__init__(
            message,
            {
                "code": "WORKFLOW_AGGREGATE_ERROR",
                "details": {"errors": error_list},
                "cause": error_list[0] if error_list else None,
            },
        )
        self.errors: List[Any] = error_list


class WorkflowPublicationError(WorkflowError):
    """Publication is an infrastructure failure, not a failed test action."""

    def __init__(
        self,
        operation: str,
        path: str,
        cause: Any,
    ) -> None:
        super().__init__(
            f"Failed to {operation} at {path}: "
            f"{_error_message(cause) if cause is not None else ''}",
            {
                "code": "WORKFLOW_PUBLICATION_FAILED",
                "details": {"operation": operation, "path": path},
                "cause": cause,
            },
        )
        self.operation = operation
        self.path = path


def as_execution_error(error: Any) -> WorkflowError:
    if isinstance(error, WorkflowError):
        return error
    return WorkflowError(
        _error_message(error),
        {"code": "WORKFLOW_EXECUTION_FAILURE", "cause": error},
    )


__all__ = [
    "WorkflowAggregateError",
    "WorkflowExecutionFailure",
    "WorkflowPublicationError",
    "as_execution_error",
]
