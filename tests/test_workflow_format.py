"""Port of upstream packages/cli/tests/unit-test/workflow-format.test.ts."""

import pytest

from midscene.cli.workflow_format import (
    assert_legacy_batch_config_path,
    assert_legacy_workflow_selection,
)


def _fixture(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_accepts_only_yaml_batch_config_paths():
    assert_legacy_batch_config_path("batch.yaml")
    assert_legacy_batch_config_path("batch.yml")
    with pytest.raises(ValueError, match="midscene-test --config"):
        assert_legacy_batch_config_path("midscene.config.ts")


def test_accepts_legacy_tasks_flow_files(tmp_path):
    legacy = _fixture(
        tmp_path, "legacy.yaml", "tasks:\n  - name: old\n    flow: []\n"
    )
    assert_legacy_workflow_selection([legacy])


def test_rejects_native_and_mixed_files_together_before_execution(tmp_path):
    legacy = _fixture(tmp_path, "legacy.yaml", "tasks: []\n")
    native = _fixture(
        tmp_path, "native.yaml", "cases:\n  - name: new\n    steps: []\n"
    )
    mixed = _fixture(tmp_path, "mixed.yaml", "tasks: []\ncases: []\n")

    with pytest.raises(
        ValueError,
        match=(
            r"midscene only runs legacy tasks/flow YAML[\s\S]*"
            r"native cases/steps[\s\S]*"
            r"mixed tasks/flow and cases/steps[\s\S]*midscene-test"
        ),
    ):
        assert_legacy_workflow_selection([legacy, native, mixed])


def test_leaves_invalid_or_unrelated_yaml_to_the_legacy_parser(tmp_path):
    invalid = _fixture(tmp_path, "invalid.yaml", "tasks: [\n")
    unknown = _fixture(tmp_path, "unknown.yaml", "files: [flow.yaml]\n")
    assert_legacy_workflow_selection([invalid, unknown])
