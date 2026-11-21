"""Workflow document format classification (upstream parser/document-format.ts)."""

from typing import Any, Literal

WorkflowDocumentFormat = Literal["legacy", "legacy-batch", "native", "mixed", "unknown"]

native_workflow_root_keys = (
    "beforeAll",
    "beforeEach",
    "cases",
    "afterEach",
    "afterAll",
)


def classify_workflow_document_format(value: Any) -> WorkflowDocumentFormat:
    """Classify only the document envelope; parsing stays with the command."""
    if not isinstance(value, dict):
        return "unknown"
    has_legacy_root = "tasks" in value
    has_native_root = any(key in value for key in native_workflow_root_keys)
    if has_legacy_root and has_native_root:
        return "mixed"
    if has_legacy_root:
        return "legacy"
    if has_native_root:
        return "native"
    if isinstance(value.get("files"), list):
        return "legacy-batch"
    return "unknown"
