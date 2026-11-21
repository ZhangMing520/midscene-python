"""YAML schema, env interpolation and flow-item helpers (upstream yaml.ts + yaml/utils.ts)."""

import os
import re
from typing import Any, Dict

import yaml


# Legacy scroll-type aliases (upstream normalizeScrollType)
_SCROLL_TYPE_ALIASES = {
    "once": "singleAction",
    "untilBottom": "scrollToBottom",
    "untilTop": "scrollToTop",
    "untilRight": "scrollToRight",
    "untilLeft": "scrollToLeft",
}


_INSIGHT_COMMANDS = (
    "aiQuery",
    "aiNumber",
    "aiString",
    "aiBoolean",
    "aiAsk",
    "aiLocate",
)


_ACTION_COMMANDS = {
    "aiTap": "Tap",
    "aiRightClick": "RightClick",
    "aiMiddleClick": "MiddleClick",
    "aiDoubleClick": "DoubleClick",
    "aiHover": "Hover",
    "aiDragAndDrop": "DragAndDrop",
    "aiClearInput": "ClearInput",
    "aiLongPress": "LongPress",
    "aiSwipe": "Swipe",
    "aiAndroidBack": "AndroidBackButton",
    "aiAndroidHome": "AndroidHomeButton",
    "aiAndroidRecentApps": "AndroidRecentAppsButton",
}


_WEB_ENV_KEYS = (
    "url",
    "userAgent",
    "viewportWidth",
    "viewportHeight",
    "headless",
    "cookie",
    "extraHTTPHeaders",
    "chromeArgs",
)


_ENV_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


_TOP_LEVEL_KEY = re.compile(r"[A-Za-z_][\w-]*\s*:")


def _interpolate_env_vars(content: str) -> str:
    """Replace ${VAR} references line by line (upstream interpolateYamlScriptEnvVars).

    Inside the top-level `tasks:` block an unresolved reference is kept as-is;
    elsewhere a missing variable is an error, matching the upstream CLI.
    """
    result_lines = []
    in_tasks = False
    for line in content.split("\n"):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            result_lines.append(line)
            continue

        if len(line) == len(stripped):
            if re.match(r"tasks\s*:", stripped):
                in_tasks = True
            elif _TOP_LEVEL_KEY.match(stripped):
                in_tasks = False

        def replace(match: "re.Match[str]") -> str:
            name = match.group(1)
            value = os.environ.get(name)
            if value is not None:
                return value
            if in_tasks:
                return match.group(0)
            raise ValueError(f'Environment variable "{name}" is not defined')

        result_lines.append(_ENV_VAR_REF.sub(replace, line))
    return "\n".join(result_lines)


def parse_yaml_script(content: str) -> Dict[str, Any]:
    """Parse a YAML automation script (upstream parseYamlScript)."""
    interpolated = _interpolate_env_vars(content)
    try:
        obj = yaml.load(interpolated, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse yaml script: {e}") from e

    if not isinstance(obj, dict):
        raise ValueError("yaml script must be a mapping")

    # Upstream counts declared targets by presence, not truthiness, so an empty
    # `computer: {}` still conflicts with a web block.
    target_keys = (
        "web", "browser", "page", "target",
        "android", "ios", "harmony", "computer", "interface",
    )
    declared = [key for key in target_keys if obj.get(key) is not None]
    if len(declared) > 1:
        raise ValueError(f"only one of {'/'.join(target_keys)} can be set")

    tasks = obj.get("tasks")
    if not tasks:
        raise ValueError('property "tasks" is required in yaml script')
    if not isinstance(tasks, list):
        raise ValueError('"tasks" must be a list')

    script: Dict[str, Any] = {
        "tasks": tasks,
        "config": obj.get("config") or {},
        "agent": obj.get("agent") or {},
    }
    for key in target_keys:
        if obj.get(key) is not None:
            script[key] = obj[key]
    return script


_INSIGHT_OPTION_KEYS = (
    "domIncluded",
    "screenshotIncluded",
    "context",
    "prompt",
    "name",
    "errorMessage",
    "keepRawResponse",
    "timeout",
    "timeoutMs",
    "checkIntervalMs",
)


def _snake(name: str) -> str:
    return name[0].lower() + name[1:]


def _build_action_param(action_name: str, options: Dict[str, Any]) -> Dict[str, Any]:
    param = {k: v for k, v in options.items() if k not in ("name", "prompt", "locate")}
    locate = options.get("locate") or (
        {"prompt": options["prompt"]} if options.get("prompt") else None
    )
    if locate:
        if isinstance(locate, str):
            locate = {"prompt": locate}
        param["locate"] = locate
    return param
