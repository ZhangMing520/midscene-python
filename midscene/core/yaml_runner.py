"""YAML automation script runner.

Synced from upstream packages/core/src/yaml.ts (schema) and
yaml/{utils,player}.py equivalents (parseYamlScript + ScriptPlayer).

Supported flow items (upstream names):
  aiAct / aiAction / ai / instruction, aiAssert, aiWaitFor,
  aiQuery / aiNumber / aiString / aiBoolean / aiAsk / aiLocate,
  aiTap, aiRightClick, aiDoubleClick, aiHover, aiInput, aiKeyboardPress,
  aiScroll, aiLongPress, aiClearInput, aiSwipe (and other action names),
  sleep, javascript, recordToReport / logScreenshot.
"""

import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from .ai_model.env_config import get_midscene_run_dir

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
    declared = [
        key
        for key in ("web", "browser", "page", "target", "android", "computer")
        if obj.get(key) is not None
    ]
    if len(declared) > 1:
        raise ValueError(
            "only one of web/browser/page/target/android/computer can be set"
        )

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
    for key in ("web", "browser", "page", "target", "android", "computer"):
        if obj.get(key) is not None:
            script[key] = obj[key]
    return script


class ScriptPlayer:
    """Execute a parsed YAML script against an agent."""

    def __init__(self, script: Dict[str, Any], agent: Any):
        self.script = script
        self.agent = agent
        self.status = "init"
        self.result: Dict[str, Any] = {}
        self.failed_tasks: List[Dict[str, Any]] = []
        self.output_path: Optional[str] = None

    async def run(self) -> None:
        self.status = "running"
        config = self.script.get("config") or {}
        output = config.get("output")
        if output:
            self.output_path = output
            Path(output).parent.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = get_midscene_run_dir("output")
            self.output_path = str(
                Path(output_dir) / f"{uuid.uuid4().hex[:8]}.json"
            )

        try:
            for task in self.script["tasks"]:
                name = task.get("name", "unnamed")
                flow = task.get("flow") or []
                try:
                    for index, flow_item in enumerate(flow):
                        if not isinstance(flow_item, dict) or len(flow_item) == 0:
                            raise ValueError(
                                f"invalid flow item at index {index} in task {name}"
                            )
                        key, value = next(iter(flow_item.items()))
                        result = await self._run_flow_item(key, value)
                        if result is not _NO_RESULT:
                            capture_name = flow_item.get("name")
                            if capture_name:
                                self.result[capture_name] = result
                except Exception as e:
                    logger.error(f"task {name} failed: {e}")
                    self.failed_tasks.append({"name": name, "error": str(e)})
                    if not task.get("continueOnError"):
                        self.status = "error"
                        break
            else:
                if self.status != "error":
                    self.status = "done"
        finally:
            self._flush_result()

    def _flush_result(self) -> None:
        if not self.output_path:
            return
        try:
            import json

            Path(self.output_path).write_text(
                json.dumps(self.result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"failed to write output file: {e}")

    # -- flow item dispatch -------------------------------------------------

    async def _run_flow_item(self, key: str, value: Any) -> Any:
        agent = self.agent

        if key in ("aiAct", "aiAction", "ai", "instruction"):
            options = value if isinstance(value, dict) else {}
            prompt = (
                value
                if isinstance(value, str)
                else options.get("prompt") or options.get("instruction")
            )
            if not prompt:
                raise ValueError(f"{key} requires an instruction")
            return await agent.ai_act(prompt, options)

        if key == "aiAssert":
            options = value if isinstance(value, dict) else {}
            prompt = value if isinstance(value, str) else options.get("prompt")
            if not prompt:
                raise ValueError("aiAssert requires a prompt")
            result = await agent.ai_assert(
                prompt,
                options.get("errorMessage"),
                {**options, "keepRawResponse": True},
            )
            if result and not result["pass"]:
                raise AssertionError(result["message"] or "aiAssert failed")
            return _NO_RESULT

        if key == "aiWaitFor":
            options = dict(value) if isinstance(value, dict) else {}
            prompt = (
                value if isinstance(value, str) else options.pop("prompt", None)
            )
            if not prompt:
                raise ValueError("aiWaitFor requires a prompt")
            await agent.ai_wait_for(prompt, options)
            return _NO_RESULT

        if key in _INSIGHT_COMMANDS:
            options = value if isinstance(value, dict) else {}
            prompt = value if isinstance(value, str) else options.get("prompt")
            if prompt is None and isinstance(value, dict):
                prompt = {
                    k: v for k, v in value.items() if k not in _INSIGHT_OPTION_KEYS
                } or None
            method = getattr(agent, _snake(key))
            if key == "aiLocate":
                result = await method(prompt, options)
                return {"center": result.get("center"), "rect": result.get("rect")}
            return await method(prompt, options)

        if key == "aiInput":
            options = dict(value) if isinstance(value, dict) else {"value": value}
            locate = options.pop("locate", None) or options.pop("prompt", None)
            await agent.ai_input(locate, options)
            return _NO_RESULT

        if key == "aiKeyboardPress":
            if isinstance(value, dict):
                locate = value.get("locate")
                key_name = value.get("keyName") or (
                    value.get("prompt") if locate else None
                )
                options = {k: v for k, v in value.items() if k not in ("locate", "keyName", "prompt")}
                await agent.ai_keyboard_press(locate, {**options, "keyName": key_name})
            else:
                await agent.ai_keyboard_press(value)
            return _NO_RESULT

        if key == "aiScroll":
            options = dict(value) if isinstance(value, dict) else {}
            locate = options.pop("locate", None) or options.pop("prompt", None)
            options["scrollType"] = _SCROLL_TYPE_ALIASES.get(
                options.get("scrollType", ""), options.get("scrollType")
            )
            await agent.ai_scroll(locate, options)
            return _NO_RESULT

        if key in _ACTION_COMMANDS:
            action_name = _ACTION_COMMANDS[key]
            options = value if isinstance(value, dict) else {"prompt": value}
            param = _build_action_param(action_name, options)
            await agent._call_action_in_action_space(action_name, param)
            return _NO_RESULT

        if key == "sleep":
            ms = int(float(value))
            await agent.sleep(ms)
            return _NO_RESULT

        if key == "javascript":
            script = value.get("script") if isinstance(value, dict) else value
            if hasattr(agent.interface, "evaluate_script"):
                return await agent.interface.evaluate_script(script)
            if hasattr(agent.interface, "execute_script"):
                return await agent.interface.execute_script(script)
            raise NotImplementedError(
                "javascript flow item requires an interface with execute_script"
            )

        if key == "runGherkinScenario":
            scenario = value if isinstance(value, str) else (value or {}).get("scenario")
            if not scenario:
                raise ValueError("runGherkinScenario requires a scenario")
            await agent.run_gherkin_scenario(scenario)
            return _NO_RESULT

        if key == "Finalize":
            # Planning-only marker; nothing to execute (upstream no-op).
            return _NO_RESULT

        if key in ("terminate", "launch"):
            # Upstream only maps these shortcuts from a string value; a bool or
            # number must not be coerced into a uri like "True".
            uri = value.get("uri") if isinstance(value, dict) else value
            if not isinstance(uri, str) or not uri.strip():
                raise ValueError(f"{key} requires a non-empty uri string")
            await agent._call_action_in_action_space(key.capitalize(), {"uri": uri})
            return _NO_RESULT

        if key in ("recordToReport", "logScreenshot"):
            options = value if isinstance(value, dict) else {"content": str(value)}
            title = options.get("title") or (
                str(value) if isinstance(value, str) else "record"
            )
            agent.record_to_report(title, options)
            logger.info(f"record: {options.get('content', '')}")
            return _NO_RESULT

        raise ValueError(f"unknown flowItem in yaml: {key}")


_NO_RESULT = object()
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
