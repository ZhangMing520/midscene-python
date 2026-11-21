"""YAML automation runtime (upstream packages/core/src/yaml + yaml/)."""

from midscene.core.yaml.builder import build_yaml
from midscene.core.yaml.cleanup import run_free_fn_cleanup
from midscene.core.yaml.player import ScriptPlayer
from midscene.core.yaml.report_policy import is_yaml_report_enabled
from midscene.core.yaml.test_runner_compat import (
    collect_legacy_yaml_document,
    collect_legacy_yaml_task_document,
    compile_legacy_flow_item,
)
from midscene.core.yaml.utils import parse_yaml_script

__all__ = [
    "ScriptPlayer",
    "build_yaml",
    "collect_legacy_yaml_document",
    "collect_legacy_yaml_task_document",
    "compile_legacy_flow_item",
    "is_yaml_report_enabled",
    "parse_yaml_script",
    "run_free_fn_cleanup",
]
