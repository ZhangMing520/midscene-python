"""Agent option and batch config construction.

Upstream packages/cli/src/config-factory.ts provides ``parseConfigYaml``,
``createConfig`` and ``createFilesConfig``; the agent option builder lives next
to them here so the CLI keeps a single config module.
"""

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger

from midscene.cli.cli_utils import match_yaml_files
from midscene.cli.config_options import DEFAULT_CONFIG, pick_yaml_target_config
from midscene.core.yaml.utils import _interpolate_env_vars, resolve_web_target
from midscene.web_integration.agent_init_args import get_agent_init_args

if TYPE_CHECKING:
    from midscene.core.agent.agent_options import AgentOptions


def _build_agent_options(section: dict) -> "AgentOptions":
    from midscene.core.agent.agent_options import AgentOptions

    agent_section = section.get("agent") or {}
    init_args = get_agent_init_args(agent_section) or {}

    options: dict[str, Any] = {
        "group_name": agent_section.get("groupName", "Midscene Report"),
        "group_description": agent_section.get("groupDescription", ""),
        "generate_report": agent_section.get("generateReport", True),
        "auto_print_report_msg": agent_section.get("autoPrintReportMsg", True),
        "report_file_name": agent_section.get("reportFileName"),
        "cache_id": _extract_cache_id(agent_section.get("cache")),
        "replanning_cycle_limit": init_args.get(
            "replanningCycleLimit",
            agent_section.get("replanningCycleLimit"),
        ),
    }
    if "aiContexts" in init_args:
        options["ai_contexts"] = init_args["aiContexts"]
    if "aiActContext" in init_args:
        options["ai_act_context"] = init_args["aiActContext"]
    if "aiActionContext" in init_args:
        options["ai_action_context"] = init_args["aiActionContext"]
    if "waitAfterAction" in init_args:
        options["wait_after_action_ms"] = init_args["waitAfterAction"]
    if "screenshotShrinkFactor" in init_args:
        options["screenshot_shrink_factor"] = init_args["screenshotShrinkFactor"]

    return AgentOptions(**options)


def _extract_cache_id(cache: object) -> str | None:
    if isinstance(cache, str):
        return cache
    if isinstance(cache, dict):
        return cache.get("id")
    return None


def _or_default(value: Any, default: Any) -> Any:
    return default if value is None else value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` over ``base`` (upstream lodash.merge)."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


async def expand_file_patterns(patterns: list, base_path: str) -> list:
    """Expand each glob, keeping duplicates and their order (upstream)."""
    all_files = []
    for pattern in patterns:
        try:
            yaml_files = match_yaml_files(pattern, {"cwd": base_path})
            all_files.extend(yaml_files)
        except Exception as error:
            logger.warning(f'Warning: Failed to expand pattern "{pattern}": {error}')
    return all_files


async def resolve_setup_file(setup: str | None, base_path: str) -> str | None:
    """Resolve the optional single setup file (upstream resolveSetupFile)."""
    if not setup:
        return None
    matched = await expand_file_patterns([setup], base_path)
    if len(matched) == 0:
        raise ValueError(f'No YAML file found matching "setup": {setup}')
    if len(matched) > 1:
        raise ValueError(
            f'"setup" must reference a single YAML file, but "{setup}" '
            f"matched {len(matched)} files"
        )
    return matched[0]


async def parse_config_yaml(config_yaml_path: str) -> dict[str, Any]:
    """Parse a batch config YAML file (upstream parseConfigYaml)."""
    base_path = os.path.dirname(os.path.abspath(config_yaml_path))
    config_content = Path(config_yaml_path).read_text(encoding="utf-8")
    interpolated_content = _interpolate_env_vars(config_content)
    try:
        config_yaml = yaml.safe_load(interpolated_content)
    except Exception as error:
        raise ValueError(f"Failed to parse config YAML: {error}") from error

    if not isinstance(config_yaml, dict) or not isinstance(
        config_yaml.get("files"), list
    ):
        raise ValueError('Config YAML must contain a "files" array')

    resolve_web_target(config_yaml)

    files = await expand_file_patterns(config_yaml["files"], base_path)
    if len(files) == 0:
        raise ValueError('No YAML files found matching the patterns in "files"')

    setup = await resolve_setup_file(config_yaml.get("setup"), base_path)

    config_file_name = os.path.splitext(os.path.basename(config_yaml_path))[0]
    default_summary = f"{config_file_name}-{_timestamp_ms()}.json"

    return {
        **pick_yaml_target_config(config_yaml),
        "concurrent": _or_default(
            config_yaml.get("concurrent"), DEFAULT_CONFIG["concurrent"]
        ),
        "continueOnError": _or_default(
            config_yaml.get("continueOnError"),
            DEFAULT_CONFIG["continueOnError"],
        ),
        "retry": _or_default(config_yaml.get("retry"), DEFAULT_CONFIG["retry"]),
        "summary": _or_default(config_yaml.get("summary"), default_summary),
        "shareBrowserContext": _or_default(
            config_yaml.get("shareBrowserContext"),
            DEFAULT_CONFIG["shareBrowserContext"],
        ),
        "reusePage": _or_default(
            config_yaml.get("reusePage"), DEFAULT_CONFIG["reusePage"]
        ),
        "patterns": config_yaml["files"],
        "files": files,
        "setup": setup,
        "headed": _or_default(config_yaml.get("headed"), DEFAULT_CONFIG["headed"]),
        "keepWindow": _or_default(
            config_yaml.get("keepWindow"), DEFAULT_CONFIG["keepWindow"]
        ),
        "dotenvOverride": _or_default(
            config_yaml.get("dotenvOverride"), DEFAULT_CONFIG["dotenvOverride"]
        ),
        "dotenvDebug": _or_default(
            config_yaml.get("dotenvDebug"), DEFAULT_CONFIG["dotenvDebug"]
        ),
    }


async def create_config(
    config_yaml_path: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Merge a batch config file with command-line options (upstream
    createConfig)."""
    options = options or {}
    parsed_config = await parse_config_yaml(config_yaml_path)
    global_config = _deep_merge(
        pick_yaml_target_config(parsed_config),
        pick_yaml_target_config(options),
    )

    keep_window = _or_default(options.get("keepWindow"), parsed_config["keepWindow"])
    headed = _or_default(options.get("headed"), parsed_config["headed"])
    final_headed = bool(keep_window or headed)

    files = parsed_config["files"]
    if options.get("files"):
        base_path = os.path.dirname(os.path.abspath(config_yaml_path))
        files = await expand_file_patterns(options["files"], base_path)

    setup = parsed_config["setup"]
    if options.get("setup"):
        base_path = os.path.dirname(os.path.abspath(config_yaml_path))
        setup = await resolve_setup_file(options["setup"], base_path)

    return {
        "files": files,
        "setup": setup,
        "concurrent": _or_default(
            options.get("concurrent"), parsed_config["concurrent"]
        ),
        "continueOnError": _or_default(
            options.get("continueOnError"), parsed_config["continueOnError"]
        ),
        "retry": _or_default(options.get("retry"), parsed_config["retry"]),
        "summary": _or_default(options.get("summary"), parsed_config["summary"]),
        "shareBrowserContext": _or_default(
            options.get("shareBrowserContext"),
            parsed_config["shareBrowserContext"],
        ),
        "reusePage": _or_default(options.get("reusePage"), parsed_config["reusePage"]),
        "headed": final_headed,
        "keepWindow": keep_window,
        "dotenvOverride": _or_default(
            options.get("dotenvOverride"), parsed_config["dotenvOverride"]
        ),
        "dotenvDebug": _or_default(
            options.get("dotenvDebug"), parsed_config["dotenvDebug"]
        ),
        "globalConfig": global_config,
    }


async def create_files_config(
    patterns: list, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a batch config from CLI patterns (upstream createFilesConfig)."""
    options = options or {}
    base_path = os.getcwd()
    files = await expand_file_patterns(patterns, base_path)
    setup = await resolve_setup_file(options.get("setup"), base_path)
    default_summary = f"summary-{_timestamp_ms()}.json"

    keep_window = _or_default(options.get("keepWindow"), DEFAULT_CONFIG["keepWindow"])
    headed = _or_default(options.get("headed"), DEFAULT_CONFIG["headed"])
    final_headed = bool(keep_window or headed)

    return {
        "files": files,
        "setup": setup,
        "concurrent": _or_default(
            options.get("concurrent"), DEFAULT_CONFIG["concurrent"]
        ),
        "continueOnError": _or_default(
            options.get("continueOnError"), DEFAULT_CONFIG["continueOnError"]
        ),
        "retry": _or_default(options.get("retry"), DEFAULT_CONFIG["retry"]),
        "summary": _or_default(options.get("summary"), default_summary),
        "shareBrowserContext": _or_default(
            options.get("shareBrowserContext"),
            DEFAULT_CONFIG["shareBrowserContext"],
        ),
        "reusePage": _or_default(options.get("reusePage"), DEFAULT_CONFIG["reusePage"]),
        "headed": final_headed,
        "keepWindow": keep_window,
        "dotenvOverride": _or_default(
            options.get("dotenvOverride"), DEFAULT_CONFIG["dotenvOverride"]
        ),
        "dotenvDebug": _or_default(
            options.get("dotenvDebug"), DEFAULT_CONFIG["dotenvDebug"]
        ),
        "globalConfig": pick_yaml_target_config(options),
    }
