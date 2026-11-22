"""YAML schema, env interpolation and flow-item helpers (upstream yaml.ts + yaml/utils.ts)."""

import os
import re
from typing import Any, Dict, List, Optional

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

_WEB_TARGET_SOURCES = ("page", "browser", "web", "target")


def resolve_web_target(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the single web target section (upstream resolveWebTarget)."""
    entries = [
        (source, config[source])
        for source in _WEB_TARGET_SOURCES
        if source in config
    ]

    if not entries:
        return None

    if len(entries) > 1:
        specified = ", ".join(source for source, _ in entries)
        raise ValueError(
            "[midscene] Only one web target can be specified, but found "
            f"multiple: {specified}. Please specify only one of: page, "
            "browser, web, or target."
        )

    source, target = entries[0]
    explicit_mode = target.get("mode") if isinstance(target, dict) else None
    if explicit_mode not in (None, "page", "browser"):
        raise ValueError(
            "[midscene] web target mode must be either \"page\" or "
            f"\"browser\", but got \"{explicit_mode}\"."
        )
    if source == "page" and explicit_mode == "browser":
        raise ValueError(
            "[midscene] page target cannot use mode: browser. Use browser: "
            "instead."
        )
    if source == "browser" and explicit_mode == "page":
        raise ValueError(
            "[midscene] browser target cannot use mode: page. Use page: "
            "instead."
        )

    mode = (
        "page"
        if source == "page"
        else "browser"
        if source == "browser"
        else explicit_mode or "page"
    )
    return {
        "source": source,
        "mode": mode,
        "target": {**(target or {}), "mode": mode},
    }


def resolve_yaml_output_config(script: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy output settings with target-local values taking priority."""
    resolved = resolve_web_target(script)
    target = (
        (resolved or {}).get("target")
        or script.get("android")
        or script.get("ios")
        or script.get("harmony")
        or script.get("computer")
    )
    config = script.get("config") or {}
    target = target or {}
    return {
        "output": (
            target.get("output")
            if target.get("output") is not None
            else config.get("output")
        ),
        "unstableLogContent": (
            target.get("unstableLogContent")
            if target.get("unstableLogContent") is not None
            else config.get("unstableLogContent")
        ),
    }


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


def parse_yaml_script(content: str, file_path: Optional[str] = None) -> Dict[str, Any]:
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


_MULTIMODAL_LOCATE_KEYS = ("images", "convertHttpImage2Base64")


def _extract_multimodal_prompt(opt: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(opt, dict):
        return None
    entries = {
        key: opt[key]
        for key in _MULTIMODAL_LOCATE_KEYS
        if opt.get(key) is not None
    }
    return entries or None


def build_detailed_locate_param(
    locate_prompt: Any, opt: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Build the canonical locate param (upstream buildDetailedLocateParam)."""
    from midscene.core.agent.prompt_context import (
        build_locate_prompt_with_context,
    )

    normalized = locate_prompt
    if isinstance(locate_prompt, dict) and "prompt" in locate_prompt:
        inner_prompt = locate_prompt["prompt"]
        rest = {key: value for key, value in locate_prompt.items() if key != "prompt"}
        normalized = locate_prompt if rest else inner_prompt

    prompt = normalized or (opt or {}).get("prompt") or (opt or {}).get("locate")
    deep_locate = False
    cacheable = True
    xpath = None

    if isinstance(opt, dict):
        # Backward-compatible: accept `deepThink` as a deprecated alias.
        deep_locate = opt.get("deepLocate")
        if deep_locate is None:
            deep_locate = opt.get("deepThink")
        if deep_locate is None:
            deep_locate = False
        cacheable = opt.get("cacheable")
        if cacheable is None:
            cacheable = True
        xpath = opt.get("xpath")

    if not prompt:
        return None

    prompt_display = prompt if isinstance(prompt, str) else prompt.get("prompt")
    context = None
    if isinstance(opt, dict) and isinstance(opt.get("context"), str):
        context = opt["context"].strip() or None
    prompt = build_locate_prompt_with_context(prompt, (opt or {}).get("context"))

    multimodal = _extract_multimodal_prompt(opt)
    if multimodal:
        if isinstance(prompt, str):
            prompt = {"prompt": prompt, **multimodal}
        else:
            prompt = {**prompt, **multimodal}

    result: Dict[str, Any] = {"prompt": prompt}
    if context:
        result["promptDisplay"] = prompt_display
        result["context"] = context
    result["deepLocate"] = deep_locate
    result["cacheable"] = cacheable
    result["xpath"] = xpath
    return result


def build_detailed_locate_param_and_rest_params(
    locate_prompt: Any,
    opt: Optional[Dict[str, Any]],
    exclude_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Split locate fields from action params (upstream buildDetailedLocateParamAndRestParams)."""
    multimodal = _extract_multimodal_prompt(opt)
    locate_param = build_detailed_locate_param(locate_prompt, opt)
    rest_params: Dict[str, Any] = {}
    if isinstance(opt, dict):
        locate_param_keys = set(locate_param or {})
        locate_prompt_value = (locate_param or {}).get("prompt")
        multimodal_keys = (
            set(multimodal or {}) if isinstance(locate_prompt_value, dict) else set()
        )
        for key, value in opt.items():
            if (
                key not in locate_param_keys
                and key != "context"
                and key != "deepThink"
                and key not in multimodal_keys
                and key not in (exclude_keys or [])
                and key != "locate"
            ):
                rest_params[key] = value
    return {"locateParam": locate_param, "restParams": rest_params}


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
