"""Workflow parser (upstream packages/core/src/test-runner/parser)."""

from midscene.core.test_runner.parser.document_format import (
    native_workflow_root_keys,
    classify_workflow_document_format,
)
from midscene.core.test_runner.parser.normalize import normalize_step, normalize_steps

__all__ = [
    "classify_workflow_document_format",
    "native_workflow_root_keys",
    "normalize_step",
    "normalize_steps",
]
