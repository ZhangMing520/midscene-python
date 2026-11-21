"""Internal YAML compatibility surface (upstream packages/core/src/yaml-runtime.ts).

Keeps parser- and format-specific APIs out of the shared Test Runner kernel.
"""

from midscene.core.yaml.execution_session import (
    enter_yaml_action,
    enter_yaml_execution,
    run_in_yaml_execution_context,
)
from midscene.core.yaml.player_state import get_legacy_yaml_player_state
from midscene.core.yaml.report_policy import is_yaml_report_enabled
from midscene.core.yaml.test_runner_compat import collect_legacy_yaml_document
from midscene.core.yaml.test_runner_nodes import (
    LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    get_legacy_yaml_result_data,
)
from midscene.core.yaml.utils import parse_yaml_script as parse_legacy_yaml_script

__all__ = [
    "LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS",
    "collect_legacy_yaml_document",
    "enter_yaml_action",
    "enter_yaml_execution",
    "get_legacy_yaml_player_state",
    "get_legacy_yaml_result_data",
    "is_yaml_report_enabled",
    "parse_legacy_yaml_script",
    "run_in_yaml_execution_context",
]
