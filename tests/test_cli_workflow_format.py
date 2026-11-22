"""Tests for legacy workflow format detection (upstream workflow-format.ts)."""

import pytest

from midscene.cli.cli_utils import _is_batch_config
from midscene.cli.workflow_format import (
    assert_legacy_batch_config_path,
    assert_legacy_workflow_selection,
    is_legacy_yaml_path,
    probe_workflow_format,
)


@pytest.mark.parametrize(
    "content,expected",
    [
        ("tasks:\n  - name: demo\n    flow:\n      - ai: hello\n", "legacy"),
        ("cases:\n  - name: demo\n    steps:\n      - ai: hello\n", "native"),
        ("tasks: []\ncases: []\n", "mixed"),
        ("files:\n  - a.yaml\n  - b.yaml\n", "legacy-batch"),
        ("just-a-scalar\n", "unknown"),
    ],
)
def test_probe_workflow_format_classifies_documents(tmp_path, content, expected):
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(content, encoding="utf-8")

    assert probe_workflow_format(str(workflow)) == expected


def test_probe_workflow_format_masks_env_placeholders(tmp_path):
    workflow = tmp_path / "env.yaml"
    workflow.write_text(
        "tasks:\n  - name: ${TASK_NAME}\n    flow:\n      - ai: ${ACTION}\n",
        encoding="utf-8",
    )

    assert probe_workflow_format(str(workflow)) == "legacy"


def test_probe_workflow_format_returns_unknown_for_unreadable_path(tmp_path):
    assert probe_workflow_format(str(tmp_path / "missing.yaml")) == "unknown"


def test_probe_workflow_format_returns_unknown_for_invalid_yaml(tmp_path):
    workflow = tmp_path / "broken.yaml"
    workflow.write_text("tasks: [unterminated\n", encoding="utf-8")

    assert probe_workflow_format(str(workflow)) == "unknown"


def test_is_legacy_yaml_path_is_case_insensitive():
    assert is_legacy_yaml_path("script.yaml")
    assert is_legacy_yaml_path("SCRIPT.YML")
    assert not is_legacy_yaml_path("script.json")
    assert not is_legacy_yaml_path("script")


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".YAML"])
def test_assert_legacy_batch_config_path_accepts_yaml(tmp_path, suffix):
    assert_legacy_batch_config_path(str(tmp_path / f"config{suffix}"))


def test_assert_legacy_batch_config_path_rejects_non_yaml(tmp_path):
    config_path = str(tmp_path / "config.json")

    with pytest.raises(ValueError) as excinfo:
        assert_legacy_batch_config_path(config_path)

    message = str(excinfo.value)
    assert "only accepts a legacy YAML batch config" in message
    assert config_path in message


def test_assert_legacy_workflow_selection_allows_legacy_and_unknown(tmp_path):
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text("tasks:\n  - name: demo\n    flow:\n      - ai: hello\n")
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text("description: no workflow keys\n")

    assert_legacy_workflow_selection([str(legacy), str(unknown)])


def test_assert_legacy_workflow_selection_rejects_native_and_mixed(tmp_path):
    native = tmp_path / "native.yaml"
    native.write_text("cases:\n  - name: demo\n    steps:\n      - ai: hello\n")
    mixed = tmp_path / "mixed.yaml"
    mixed.write_text("tasks: []\ncases: []\n")

    with pytest.raises(ValueError) as excinfo:
        assert_legacy_workflow_selection(
            [str(native), str(mixed), str(native)]
        )

    message = str(excinfo.value)
    assert "midscene only runs legacy tasks/flow YAML." in message
    assert "native cases/steps" in message
    assert "mixed tasks/flow and cases/steps" in message
    # Resolved duplicates are classified once.
    assert message.count("native cases/steps") == 1


def test_is_batch_config_uses_legacy_extension_detection(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("files:\n  - a.yaml\n")
    text_path = tmp_path / "config.txt"
    text_path.write_text("files:\n  - a.yaml\n")

    assert _is_batch_config(yaml_path)
    assert not _is_batch_config(text_path)
