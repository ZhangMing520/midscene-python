"""Basic env access (upstream packages/shared/src/env/basic.ts).

Kept in a single module so callers can read the handful of process-level
keys without importing the model configuration layer.
"""

import os

from midscene.shared.env.constants import BASIC_ENV_KEYS


def get_basic_env_value(key: str) -> str | None:
    """Read a basic env value from the process environment."""
    if key not in BASIC_ENV_KEYS:
        raise ValueError(f"getBasicEnvValue with key {key} is not supported.")
    return os.environ.get(key)


__all__ = ["BASIC_ENV_KEYS", "get_basic_env_value"]
