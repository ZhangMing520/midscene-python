"""YAML script player (upstream yaml/player.ts)."""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.yaml.player_state import (
    get_legacy_yaml_player_state,
    initialize_legacy_yaml_player_state,
)
from midscene.core.yaml.legacy_yaml_runtime import (
    create_legacy_yaml_runtime,
    legacy_yaml_outcome_error,
)
from midscene.core.yaml.report_policy import _execution_count, _record_yaml_task_error
from midscene.core.yaml.utils import (
    _ACTION_COMMANDS,
    _INSIGHT_COMMANDS,
    _INSIGHT_OPTION_KEYS,
    _SCROLL_TYPE_ALIASES,
    _build_action_param,
    _snake,
)
from midscene.shared.env import get_midscene_run_dir


class ScriptPlayer:
    """Execute a parsed YAML script against an agent."""

    def __init__(self, script: Dict[str, Any], agent: Any):
        self.script = script
        self.agent = agent
        self.status = "init"
        self.result: Dict[str, Any] = {}
        self.failed_tasks: List[Dict[str, Any]] = []
        self.output_path: Optional[str] = None
        self.current_task_index: Optional[int] = None
        self.report_file: Optional[str] = None
        self._unnamed_result_index = 0
        initialize_legacy_yaml_player_state(self)

    def _set_result(self, key: Optional[str], value: Any) -> None:
        key_to_use = key or self._unnamed_result_index
        if not key:
            self._unnamed_result_index += 1
        self.result[key_to_use] = value

    async def play_task(self, task_status: Dict[str, Any], agent: Any) -> None:
        """Run one YAML task against ``agent`` (upstream playTask)."""
        flow = (
            task_status.get("flow")
            if isinstance(task_status, dict)
            else getattr(task_status, "flow", None)
        )
        if not flow:
            raise AssertionError("missing flow in task")

        tasks = self.script.get("tasks") or []
        try:
            task_index = tasks.index(task_status)
        except ValueError:
            declared = (
                task_status.get("index")
                if isinstance(task_status, dict)
                else getattr(task_status, "index", None)
            )
            task_index = (
                declared
                if isinstance(declared, int) and not isinstance(declared, bool)
                else 0
            )

        state = get_legacy_yaml_player_state(self)
        runtime = create_legacy_yaml_runtime(
            {
                "agent": agent,
                "actionSpace": getattr(agent, "_action_space", None) or [],
                "sourcePath": None,
                "setResult": self._set_result,
            }
        )
        execution_result = await runtime.run_task(task_status, task_index)
        state["executionResult"] = execution_result

        cases = execution_result.get("cases") or []
        outcome = cases[0] if cases else None
        if not outcome or outcome.get("status") == "not-run":
            raise RuntimeError(
                f'Task "{task_status.get("name")}" did not run.'
            )
        if outcome.get("status") == "failed":
            raise legacy_yaml_outcome_error(outcome)

        self.report_file = (
            getattr(agent, "report_file", None)
            or getattr(agent, "_report_file", None)
            or getattr(agent, "_report_finalized", None)
        )

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
                execution_count_before = _execution_count(self.agent)
                flow_index = 0
                try:
                    for index, flow_item in enumerate(flow):
                        flow_index = index
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
                    await _record_yaml_task_error(
                        self.agent, name, flow_index, e, execution_count_before
                    )
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
            result = await agent._call_action_in_action_space(action_name, param)
            return _NO_RESULT if result is None else result

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
