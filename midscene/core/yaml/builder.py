"""Build a YAML script document (upstream yaml/builder.ts)."""

from typing import Any

import yaml


def build_yaml(env: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    """Serialize a web env block plus tasks into YAML."""
    return yaml.dump({"page": env, "tasks": tasks}, indent=2, sort_keys=False)
