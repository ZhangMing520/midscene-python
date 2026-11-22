"""CLI configuration option keys (upstream packages/cli/src/config-options.ts)."""

from typing import Any, Dict

# Upstream defaultConfig.
DEFAULT_CONFIG = {
    "concurrent": 1,
    "continueOnError": False,
    "retry": 0,
    "shareBrowserContext": False,
    "reusePage": False,
    "headed": False,
    "keepWindow": False,
    "dotenvOverride": False,
    "dotenvDebug": False,
}

# Upstream midsceneYamlTargetKeys.
YAML_TARGET_KEYS = (
    "web", "page", "browser", "target",
    "android", "ios", "harmony", "computer", "interface",
)
WEB_TARGET_KEYS = ("web", "page", "browser", "target")
NATIVE_TARGET_KEYS = ("android", "ios", "harmony", "computer", "interface")


def pick_yaml_target_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only target overrides before merging them into a YAML script."""
    return {key: config[key] for key in YAML_TARGET_KEYS if key in config}


__all__ = [
    "DEFAULT_CONFIG",
    "NATIVE_TARGET_KEYS",
    "WEB_TARGET_KEYS",
    "YAML_TARGET_KEYS",
    "pick_yaml_target_config",
]
