"""YAML automation runtime (upstream packages/core/src/yaml + yaml/)."""

from midscene.core.yaml.builder import build_yaml
from midscene.core.yaml.cleanup import run_free_fn_cleanup
from midscene.core.yaml.legacy_yaml_report import publish_legacy_yaml_report
from midscene.core.yaml.legacy_yaml_runtime import (
    LegacyYamlRuntime,
    create_legacy_yaml_runtime,
    legacy_yaml_outcome_error,
)
from midscene.core.yaml.player import ScriptPlayer
from midscene.core.yaml.report_policy import is_yaml_report_enabled
from midscene.core.yaml.test_runner_compat import (
    collect_legacy_yaml_document,
    collect_legacy_yaml_task_document,
    compile_legacy_flow_item,
)
from midscene.core.yaml.test_runner_nodes import (
    LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    get_legacy_yaml_result_data,
)
from midscene.core.yaml.utils import parse_yaml_script

__all__ = [
    "LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS",
    "LegacyYamlRuntime",
    "ScriptPlayer",
    "build_yaml",
    "collect_legacy_yaml_document",
    "collect_legacy_yaml_task_document",
    "compile_legacy_flow_item",
    "create_legacy_yaml_runtime",
    "get_legacy_yaml_result_data",
    "is_yaml_report_enabled",
    "legacy_yaml_outcome_error",
    "parse_yaml_script",
    "publish_legacy_yaml_report",
    "run_free_fn_cleanup",
]
