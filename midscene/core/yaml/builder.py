"""Build a YAML script document (upstream yaml/builder.ts)."""

from typing import Any, Dict, List

import yaml


def build_yaml(env: Dict[str, Any], tasks: List[Dict[str, Any]]) -> str:
    """Serialize a web env block plus tasks into YAML."""
    return yaml.dump({"page": env, "tasks": tasks}, indent=2, sort_keys=False)
