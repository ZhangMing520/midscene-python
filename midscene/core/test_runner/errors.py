"""Workflow errors (upstream test-runner/errors.ts)."""

from typing import Any, Dict, List, Optional


class WorkflowError(Exception):
    """Base workflow error carrying a stable code and structured details."""

    code = "WORKFLOW_ERROR"

    def __init__(
        self,
        message: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        options = options or {}
        super().__init__(message)
        self.code = options.get("code") or self.code
        self.details = options.get("details")
        self.cause = options.get("cause")

    def to_json(self) -> Dict[str, Any]:
        return {
            "name": type(self).__name__,
            "message": str(self),
            "code": self.code,
            "details": self.details,
        }


class WorkflowParseError(WorkflowError):
    def __init__(self, message: str, details: Any = None, cause: Any = None) -> None:
        super().__init__(
            message, {"code": "WORKFLOW_PARSE_ERROR", "details": details, "cause": cause}
        )


class NodeDefinitionError(WorkflowError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, {"code": "NODE_DEFINITION_ERROR", "details": details})


class DuplicateNodeError(WorkflowError):
    def __init__(self, node: str) -> None:
        super().__init__(
            f'Node "{node}" is already registered.',
            {"code": "DUPLICATE_NODE", "details": {"node": node}},
        )
        self.node = node


class NodeNotFoundError(WorkflowError):
    def __init__(self, node: str) -> None:
        super().__init__(
            f'Node "{node}" is not registered.',
            {"code": "NODE_NOT_FOUND", "details": {"node": node}},
        )
        self.node = node


class NodeInputValidationError(WorkflowError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(
            message, {"code": "NODE_INPUT_VALIDATION_ERROR", "details": details}
        )

    @classmethod
    def from_validation_issues(
        cls, node: str, issues: List[Dict[str, Any]]
    ) -> "NodeInputValidationError":
        first = issues[0] if issues else {}
        path = first.get("path") or ""
        message = first.get("message") or "invalid input"
        return cls(
            f'Node "{node}" input validation failed at "{path}": {message}',
            {"node": node, "issues": issues},
        )


class StepTimeoutError(WorkflowError):
    def __init__(self, timeout_ms: int, node: Optional[str] = None) -> None:
        message = (
            f'Node "{node}" timed out after {timeout_ms}ms.'
            if node
            else f"Step timed out after {timeout_ms}ms."
        )
        details: Dict[str, Any] = {"timeoutMs": timeout_ms}
        if node is not None:
            details["node"] = node
        super().__init__(message, {"code": "STEP_TIMEOUT", "details": details})
        self.timeout_ms = timeout_ms
        self.node = node


class NodeExecutionError(WorkflowError):
    def __init__(self, node: str, cause: Any, output: Any = None) -> None:
        cause_message = str(cause) if cause is not None else "Unknown error"
        super().__init__(
            f'Node "{node}" failed: {cause_message}',
            {"code": "NODE_EXECUTION_ERROR", "details": {"node": node}, "cause": cause},
        )
        self.node = node
        self.output = output


class WorkflowLifecycleError(WorkflowError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(
            message, {"code": "WORKFLOW_LIFECYCLE_ERROR", "details": details}
        )


class ProjectSetupError(WorkflowError):
    def __init__(self, cause: Any, details: Dict[str, Any]) -> None:
        cause_message = str(cause) if cause is not None else "Unknown error"
        super().__init__(
            f'Project "{details["projectName"]}" setup failed: {cause_message}',
            {"code": "PROJECT_SETUP_ERROR", "details": details, "cause": cause},
        )


class ProjectTeardownError(WorkflowError):
    def __init__(self, cause: Any, details: Dict[str, Any]) -> None:
        cause_message = str(cause) if cause is not None else "Unknown error"
        super().__init__(
            f'Project "{details["projectName"]}" teardown failed: {cause_message}',
            {"code": "PROJECT_TEARDOWN_ERROR", "details": details, "cause": cause},
        )


class NodeScopeTeardownError(WorkflowError):
    def __init__(self, cause: Any, details: Dict[str, Any]) -> None:
        cause_message = str(cause) if cause is not None else "Unknown error"
        scope = "Case attempt" if details.get("scope") == "case" else "Workflow document"
        super().__init__(
            f'{scope} node teardown failed for "{details.get("node")}": {cause_message}',
            {"code": "NODE_SCOPE_TEARDOWN_ERROR", "details": details, "cause": cause},
        )


class FatalDeviceError(WorkflowError):
    def __init__(self, message: str, cause: Any = None) -> None:
        super().__init__(
            message, {"code": "FATAL_DEVICE_ERROR", "cause": cause}
        )


class CaseExecutionError(WorkflowError):
    def __init__(self, result: Any) -> None:
        name = getattr(result, "name", "case")
        super().__init__(
            f'Case "{name}" failed.',
            {
                "code": "CASE_EXECUTION_FAILED",
                "details": {
                    "caseId": getattr(result, "caseId", None),
                    "runId": getattr(result, "runId", None),
                },
            },
        )
        self.result = result


class WorkflowDocumentExecutionError(WorkflowError):
    def __init__(self, result: Any) -> None:
        super().__init__(
            f'Workflow document "{getattr(result, "sourcePath", "")}" failed.',
            {
                "code": "WORKFLOW_DOCUMENT_EXECUTION_FAILED",
                "details": {
                    "documentId": getattr(result, "documentId", None),
                    "documentRunId": getattr(result, "documentRunId", None),
                },
            },
        )
        self.result = result


_FATAL_DEVICE_MESSAGE = (
    r"device offline|device not found|(?:adb|bdc|device) connection (?:was )?closed"
)


def is_workflow_error(error: Any) -> bool:
    return isinstance(error, WorkflowError)


def is_node_execution_error(error: Any) -> bool:
    return isinstance(error, NodeExecutionError)


def normalize_node_execution_error(error: Any, node: str) -> WorkflowError:
    return error if is_workflow_error(error) else NodeExecutionError(node, error)


def is_fatal_device_error(error: Any) -> bool:
    import re

    pattern = re.compile(_FATAL_DEVICE_MESSAGE, re.IGNORECASE)
    seen: set = set()
    pending: List[Any] = [error]
    while pending and len(seen) < 50:
        current = pending.pop()
        if not isinstance(current, WorkflowError) and not isinstance(current, BaseException):
            continue
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, FatalDeviceError) or getattr(current, "code", None) == "FATAL_DEVICE_ERROR":
            return True
        if pattern.search(str(current)):
            return True
        cause = getattr(current, "cause", None)
        if cause is not None:
            pending.append(cause)
        nested = getattr(current, "errors", None)
        if isinstance(nested, (list, tuple)):
            pending.extend(list(nested)[:50])
    return False


def is_resource_recovery_error(error: Any) -> bool:
    return is_workflow_error(error) and error.code == "RESOURCE_RECOVERY_TIMEOUT"
