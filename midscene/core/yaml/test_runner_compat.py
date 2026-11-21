"""Compile legacy YAML flow items into Runner IR (upstream yaml/test-runner-compat.ts)."""

import math
import re
from typing import Any, Dict, List, Optional

from midscene.core.test_runner.parser.types import (
    CollectedCase,
    CollectedWorkflowDocument,
    NormalizedStep,
)
from midscene.core.yaml.utils import (
    build_detailed_locate_param,
    build_detailed_locate_param_and_rest_params,
)

_INSIGHT_NODES = (
    "aiQuery",
    "aiNumber",
    "aiString",
    "aiBoolean",
    "aiAsk",
    "aiLocate",
)


def _action_attr(action: Any, key: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        return action.get(key, default)
    return getattr(action, key, default)


def _is_string_param_schema(schema: Any) -> bool:
    """Best-effort check for scalar string action params.

    Python action schemas are plain dicts rather than Zod definitions, so the
    check only covers the scalar shapes the YAML shortcut relies on.
    """
    if not schema:
        return False
    if isinstance(schema, str):
        return schema == "string"
    if not isinstance(schema, dict):
        return False
    type_name = schema.get("type") or schema.get("typeName")
    if type_name in ("ZodString", "string", "ZodEnum", "enum", "nativeEnum"):
        return True
    if type_name in ("ZodLiteral", "literal"):
        return isinstance(schema.get("value"), str)
    if type_name in (
        "ZodOptional",
        "ZodNullable",
        "ZodDefault",
        "optional",
        "nullable",
        "default",
    ):
        inner = (
            schema.get("innerType")
            or schema.get("inner")
            or schema.get("schema")
        )
        return _is_string_param_schema(inner)
    if type_name in ("ZodEffects", "effects"):
        return _is_string_param_schema(schema.get("schema"))
    if type_name in ("ZodPipeline", "pipeline"):
        return _is_string_param_schema(schema.get("out"))
    if type_name in ("ZodUnion", "union"):
        options = schema.get("options")
        return isinstance(options, list) and all(
            _is_string_param_schema(option) for option in options
        )
    return False


def _build_shortcut_action_param(
    action_name: str, interface_alias: Optional[str], value: str
) -> Optional[Dict[str, str]]:
    if action_name == "Launch" or interface_alias == "launch":
        return {"uri": value}
    if action_name == "Terminate" or interface_alias == "terminate":
        return {"uri": value}
    if (
        action_name == "RunAdbShell"
        or interface_alias == "runAdbShell"
        or action_name == "RunHdcShell"
        or interface_alias == "runHdcShell"
    ):
        return {"command": value}
    return None


def _has_prompt(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, dict):
        return isinstance(value.get("prompt"), str) and bool(value["prompt"])
    return False


def compile_legacy_flow_item(
    flow_item: Any,
    action_space: Optional[List[Any]] = None,
) -> NormalizedStep:
    """Translate known syntax; defer ActionSpace-dependent grammar to the YAML host."""
    action_space = action_space or []
    if not isinstance(flow_item, dict):
        return {
            "node": "legacyValidationError",
            "input": {"message": "flow item must be an object"},
            "meta": {"continueOnError": False},
        }
    raw = flow_item
    name = raw.get("name")
    flow = {key: value for key, value in raw.items() if key != "name"}

    def step(
        node: str, input_value: Dict[str, Any], capture_result: bool = False
    ) -> NormalizedStep:
        meta: Dict[str, Any] = {"continueOnError": False}
        if capture_result:
            meta["captureResult"] = True
            if isinstance(name, str) and name:
                meta["resultName"] = name
        return {"node": node, "input": input_value, "meta": meta}

    def invalid(message: str) -> NormalizedStep:
        return step("legacyValidationError", {"message": message})

    if "Finalize" in flow:
        return step("Finalize", {})
    if "aiAct" in flow or "aiAction" in flow or "ai" in flow:
        options = {
            key: value
            for key, value in raw.items()
            if key not in ("aiAct", "aiAction", "ai", "instruction")
        }
        action_prompt = raw.get("aiAct")
        if action_prompt is None:
            action_prompt = raw.get("aiAction")
        if action_prompt is None:
            action_prompt = raw.get("ai")
        instruction = raw.get("instruction")
        if _has_prompt(instruction):
            prompt = instruction
        elif _has_prompt(action_prompt):
            prompt = action_prompt
        else:
            prompt = None
        if prompt:
            return step("aiAct", {"prompt": prompt, "options": options})
        return invalid("missing prompt for ai (aiAct)")
    if "runGherkinScenario" in flow:
        scenario = flow["runGherkinScenario"]
        if scenario:
            return step(
                "runGherkinScenario",
                {"scenario": scenario, "options": {"cacheable": False}},
            )
        return invalid("missing scenario for runGherkinScenario")
    if "aiAssert" in flow:
        prompt = flow["aiAssert"]
        message = flow.get("errorMessage")
        options = {
            key: value
            for key, value in flow.items()
            if key not in ("aiAssert", "errorMessage")
        }
        if not prompt:
            return invalid("missing prompt for aiAssert")
        if "observe" in raw:
            return invalid(
                "`observe` is not supported in YAML aiAssert. Use "
                "agent.startObserving() from code instead."
            )
        return step(
            "aiAssert",
            {
                "prompt": prompt,
                "options": {**options, "keepRawResponse": True},
                "message": message,
            },
            True,
        )
    for node in _INSIGHT_NODES:
        if node in flow:
            prompt = flow[node]
            options = {
                key: value for key, value in flow.items() if key != node
            }
            if not prompt:
                return invalid(f"missing prompt for {node}")
            if "observe" in raw:
                return invalid(
                    "`observe` is not supported in YAML flow items. Use "
                    "agent.startObserving() from code instead."
                )
            return step(node, {"prompt": prompt, "options": options}, True)
    if "aiWaitFor" in flow:
        prompt = raw.get("aiWaitFor")
        timeout = raw.get("timeout")
        options = {
            key: value
            for key, value in raw.items()
            if key not in ("aiWaitFor", "timeout")
        }
        if not prompt:
            return invalid("missing prompt for aiWaitFor")
        if timeout is not None:
            options["timeout"] = timeout
            options["timeoutMs"] = timeout
        return step("aiWaitFor", {"prompt": prompt, "options": options})
    if "sleep" in flow:
        raw_sleep = flow["sleep"]
        if isinstance(raw_sleep, str):
            match = re.match(r"^\s*[+-]?\d+", raw_sleep)
            ms = int(match.group(0)) if match else float("nan")
        else:
            ms = raw_sleep
        # The old player rejected invalid sleep only when execution reached it.
        # Keep both that timing and its error message inside the YAML boundary.
        if (
            isinstance(ms, bool)
            or not isinstance(ms, (int, float))
            or not math.isfinite(ms)
            or ms <= 0
        ):
            return invalid(
                f"ms for sleep must be greater than 0, but got {raw_sleep}"
            )
        return step("sleep", {"ms": ms})
    if "javascript" in flow:
        return step("javascript", {"script": flow["javascript"]}, True)
    if "recordToReport" in flow or "logScreenshot" in flow:
        title = flow.get("recordToReport")
        if title is None:
            title = flow.get("logScreenshot")
        if title is None:
            title = "untitled"
        return step(
            "recordToReport",
            {"title": title, "options": {"content": flow.get("content") or ""}},
        )
    if "aiInput" in flow:
        ai_input = flow["aiInput"]
        raw_value = flow.get("value")
        options = {
            key: value
            for key, value in flow.items()
            if key not in ("aiInput", "value")
        }
        prompt = options.get("locate") or ai_input or ""
        value = (ai_input or raw_value) if options.get("locate") else raw_value
        params: Dict[str, Any] = dict(options)
        if value is not None:
            params["value"] = str(value)
        if prompt:
            params["locate"] = build_detailed_locate_param(prompt, options)
        return step("action", {"name": "Input", "params": params})
    if "aiKeyboardPress" in flow:
        ai_keyboard_press = flow["aiKeyboardPress"]
        options = {
            key: value for key, value in flow.items() if key != "aiKeyboardPress"
        }
        if options.get("locate"):
            prompt = options["locate"]
        elif options.get("keyName"):
            prompt = ai_keyboard_press
        else:
            prompt = None
        key_name = (
            ai_keyboard_press
            if options.get("locate")
            else options.get("keyName") or ai_keyboard_press
        )
        params = dict(options)
        if key_name:
            params["keyName"] = key_name
        if prompt:
            params["locate"] = build_detailed_locate_param(prompt, options)
        return step("action", {"name": "KeyboardPress", "params": params})
    if "aiScroll" in flow:
        ai_scroll = flow["aiScroll"]
        locate = flow.get("locate")
        options = {
            key: value
            for key, value in flow.items()
            if key not in ("aiScroll", "locate")
        }
        prompt = locate if locate is not None else ai_scroll
        return step("aiScroll", {"prompt": prompt, "options": options})
    if "aiTap" in flow:
        ai_tap = flow["aiTap"]
        prompt = flow.get("prompt")
        locate = flow.get("locate")
        tap_options = {
            key: value
            for key, value in flow.items()
            if key not in ("aiTap", "prompt", "locate")
        }
        nested = locate
        if nested is None and isinstance(ai_tap, dict):
            nested = ai_tap.get("locate")
        locate_prompt: Any = None
        options = tap_options
        if isinstance(ai_tap, str) and ai_tap:
            locate_prompt = ai_tap
        elif isinstance(nested, dict) and nested.get("prompt"):
            nested_prompt = nested.get("prompt")
            nested_options = {
                key: value for key, value in nested.items() if key != "prompt"
            }
            locate_prompt = nested_prompt
            options = {**nested_options, **tap_options}
        elif (
            isinstance(ai_tap, dict)
            and isinstance(ai_tap.get("prompt"), str)
            and ai_tap["prompt"]
        ):
            # Keep structured prompt data such as images inside the private
            # YAML adapter. A prompt-only object retains the normalized string.
            locate_prompt = (
                ai_tap
                if ("images" in ai_tap or "convertHttpImage2Base64" in ai_tap)
                else ai_tap["prompt"]
            )
        else:
            locate_prompt = prompt or nested
        if locate_prompt:
            return step("aiTap", {"prompt": locate_prompt, "options": options})
        return invalid("missing prompt for aiTap")
    if isinstance(flow.get("runAdbShell"), str) and isinstance(
        flow.get("timeout"), (int, float)
    ) and not isinstance(flow.get("timeout"), bool):
        return step(
            "runAdbShell",
            {"command": flow["runAdbShell"], "timeout": flow["timeout"]},
            True,
        )
    action = next(
        (
            item
            for item in action_space
            if (
                _action_attr(item, "interface_alias")
                and _action_attr(item, "interface_alias") in flow
            )
            or _action_attr(item, "name") in flow
        ),
        None,
    )
    if action is None:
        return step("legacyAction", {"flow": flow}, True)
    action_name = _action_attr(action, "name")
    interface_alias = _action_attr(action, "interface_alias")
    key = (
        interface_alias
        if interface_alias and interface_alias in flow
        else action_name
    )
    value = flow.get(key)
    if isinstance(value, str):
        shortcut = _build_shortcut_action_param(
            action_name, interface_alias, value
        )
        if shortcut:
            return step(
                "action", {"name": action_name, "params": shortcut}, True
            )
        if _is_string_param_schema(_action_attr(action, "param_schema")):
            return step("action", {"name": action_name, "params": value}, True)
    prompt = value if isinstance(value, str) else ""
    if prompt:
        source: Any = {**flow, "prompt": prompt}
    elif isinstance(value, dict):
        source = value
    else:
        source = flow
    locate = build_detailed_locate_param_and_rest_params(
        prompt, source, [action_name, interface_alias or ""]
    )
    return step(
        "action",
        {
            "name": action_name,
            "params": {**locate["restParams"], "locate": locate["locateParam"]},
        },
        True,
    )


def _legacy_document_id(source_path: str) -> str:
    return f"legacy-yaml:{source_path}"


def collect_legacy_yaml_task(
    task: Dict[str, Any],
    task_index: int,
    source_path: str = "<inline-yaml>",
    action_space: Optional[List[Any]] = None,
) -> CollectedCase:
    """Compile one legacy task into a Runner Case with its original task index."""
    document_id = _legacy_document_id(source_path)
    flow = task.get("flow")
    if isinstance(flow, list):
        steps = [
            compile_legacy_flow_item(flow_item, action_space)
            for flow_item in flow
        ]
    else:
        steps = [
            {
                "node": "legacyValidationError",
                "input": {"message": "missing flow in task"},
                "meta": {"continueOnError": False},
            }
        ]
    return {
        "caseId": f"{document_id}:task:{task_index}",
        "projectId": "legacy-yaml",
        "sourcePath": source_path,
        "caseIndex": task_index,
        "definition": {
            "name": task.get("name"),
            "onFailure": (
                "continue" if task.get("continueOnError") else "stop-document"
            ),
            "steps": steps,
        },
    }


def _legacy_yaml_document(
    source_path: str, cases: List[CollectedCase]
) -> CollectedWorkflowDocument:
    return {
        "documentId": _legacy_document_id(source_path),
        "projectId": "legacy-yaml",
        "sourcePath": source_path,
        "lifecycle": {
            "beforeAll": [],
            "beforeEach": [],
            "afterEach": [],
            "afterAll": [],
        },
        "cases": cases,
    }


def collect_legacy_yaml_task_document(
    task: Dict[str, Any],
    task_index: int,
    source_path: str = "<inline-yaml>",
    action_space: Optional[List[Any]] = None,
) -> CollectedWorkflowDocument:
    """Compile one legacy task into a one-Case Runner document."""
    return _legacy_yaml_document(
        source_path,
        [
            collect_legacy_yaml_task(
                task, task_index, source_path, action_space
            )
        ],
    )


def collect_legacy_yaml_document(
    script: Dict[str, Any],
    source_path: str = "<inline-yaml>",
    action_space: Optional[List[Any]] = None,
    identity: Optional[CollectedWorkflowDocument] = None,
) -> CollectedWorkflowDocument:
    """Compile the legacy tasks/flow shape into the Runner document/case/step IR."""
    document = _legacy_yaml_document(
        source_path,
        [
            collect_legacy_yaml_task(
                task, task_index, source_path, action_space
            )
            for task_index, task in enumerate(script.get("tasks") or [])
        ],
    )
    if identity is None:
        return document
    by_index = {
        case["caseIndex"]: case["caseId"] for case in identity.get("cases") or []
    }
    return {
        **document,
        "documentId": identity.get("documentId"),
        "projectId": identity.get("projectId"),
        "cases": [
            {
                **item,
                "projectId": identity.get("projectId"),
                "caseId": by_index[item["caseIndex"]],
            }
            for item in document["cases"]
        ],
    }


__all__ = [
    "compile_legacy_flow_item",
    "collect_legacy_yaml_document",
    "collect_legacy_yaml_task",
    "collect_legacy_yaml_task_document",
]
