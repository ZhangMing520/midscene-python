"""Workflow format detection for the legacy YAML CLI.

Aligned with upstream ``packages/cli/src/workflow-format.ts``. The legacy
``midscene run`` command only accepts ``tasks``/``flow`` documents, while
native ``cases``/``steps`` projects belong to ``midscene-test``. These
helpers classify files before any browser, device, or Agent is created.
"""

import re
from collections.abc import Iterable
from pathlib import Path

from midscene.core.test_runner.parser.document_format import (
    WorkflowDocumentFormat,
    classify_workflow_document_format,
)

LEGACY_YAML_EXTENSIONS = (".yaml", ".yml")

_ENV_PLACEHOLDER = re.compile(r"\$\{[^}\r\n]*\}")


def is_legacy_yaml_path(path: str) -> bool:
    """True when `path` uses a legacy YAML extension (case-insensitive)."""
    return Path(path).suffix.lower() in LEGACY_YAML_EXTENSIONS


def probe_workflow_format(file: str) -> WorkflowDocumentFormat:
    """Classify a workflow file without executing it.

    Environment placeholders are masked before parsing (upstream replaces
    ``${...}`` with ``MIDSCENE_ENV``). Load failures return ``"unknown"``
    because the legacy parser remains responsible for syntax and schema
    errors.
    """
    try:
        import yaml

        content = Path(file).read_text(encoding="utf-8")
        content = _ENV_PLACEHOLDER.sub("MIDSCENE_ENV", content)
        return classify_workflow_document_format(yaml.safe_load(content))
    except Exception:
        return "unknown"


def assert_legacy_batch_config_path(config_path: str) -> None:
    """Reject non-YAML paths passed to ``midscene --config``."""
    if not is_legacy_yaml_path(config_path):
        raise ValueError(
            "midscene --config only accepts a legacy YAML batch config: "
            f"{config_path}. Run a native Test project config with "
            f"`midscene-test --config {config_path}`."
        )


def assert_legacy_workflow_selection(files: Iterable[str]) -> None:
    """Reject native/mixed workflow documents before any Agent is created."""
    native_files = []
    mixed_files = []
    seen = set()
    for item in files:
        resolved = str(Path(item).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        workflow_format = probe_workflow_format(resolved)
        if workflow_format == "native":
            native_files.append(resolved)
        elif workflow_format == "mixed":
            mixed_files.append(resolved)

    if not native_files and not mixed_files:
        return

    details = [f"- native cases/steps: {item}" for item in native_files]
    details.extend(
        f"- mixed tasks/flow and cases/steps: {item}" for item in mixed_files
    )
    raise ValueError(
        "\n".join(
            [
                "midscene only runs legacy tasks/flow YAML.",
                *details,
                "Run native files with `midscene-test`, and keep legacy and "
                "native formats in separate files and command invocations.",
            ]
        )
    )


__all__ = [
    "LEGACY_YAML_EXTENSIONS",
    "assert_legacy_batch_config_path",
    "assert_legacy_workflow_selection",
    "is_legacy_yaml_path",
    "probe_workflow_format",
]
