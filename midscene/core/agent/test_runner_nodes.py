"""Agent-owned Test Runner nodes (upstream agent/test-runner-nodes.ts).

The TypeScript module validates inputs with zod schemas. Python action inputs
are plain mappings here (the workflow engine treats dict schemas as
passthrough), so each definition only carries the field contract used by the
YAML compatibility layer.

Node names stay in upstream camelCase because YAML documents reference them;
the Python agent methods they call are snake_case.
"""

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from midscene.core.agent.observe_node import execute_observe
from midscene.core.test_runner.errors import NodeExecutionError


@dataclass
class AgentTestRunnerNodeExecutionContext:
    signal: Any = None


@dataclass
class AgentTestRunnerNodeDefinition:
    """Agent-owned Node description consumed by Test Runner adapters."""

    name: str
    execute: Callable[[Any, Dict[str, Any], AgentTestRunnerNodeExecutionContext], Any]
    title: Optional[str] = None
    description: Optional[str] = None
    # Node input field populated by YAML string shorthand; False disables it.
    string_input_key: Optional[Union[str, bool]] = None
    input_schema: Optional[Dict[str, Any]] = None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def create_agent_test_runner_node_definition(
    agent_label: str = "an Agent",
) -> Callable[[Dict[str, Any]], AgentTestRunnerNodeDefinition]:
    """Create a Node factory whose adapters are checked against an Agent API."""

    def define(options: Dict[str, Any]) -> AgentTestRunnerNodeDefinition:
        method = options["method"]
        to_args = options["to_args"]
        to_result = options.get("to_result")

        async def execute(
            agent: Any,
            input_value: Dict[str, Any],
            context: AgentTestRunnerNodeExecutionContext,
        ) -> Any:
            bound = getattr(agent, method, None) if agent is not None else None
            if not callable(bound):
                raise TypeError(
                    f"getAgent() must return {agent_label} with {method}()."
                )
            result = await _maybe_await(bound(*to_args(input_value, context)))
            if to_result is None:
                return None
            return to_result(result, input_value)

        return AgentTestRunnerNodeDefinition(
            name=options.get("name") or method,
            execute=execute,
            title=options.get("title"),
            description=options.get("description"),
            string_input_key=options.get("string_input_key"),
            input_schema=options.get("input_schema"),
        )

    return define


def _schema(properties: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _text(description: str) -> Dict[str, Any]:
    return {"type": "string", "description": description}


_PROMPT_IMAGE = _schema(
    {
        "name": _text("The name used to identify this reference image."),
        "url": _text("The URL, data URL, or file path of this reference image."),
    },
    ["name", "url"],
)

_STRUCTURED_USER_PROMPT = _schema(
    {
        "prompt": _text("The natural-language prompt."),
        "images": {"type": "array", "items": _PROMPT_IMAGE, "minItems": 1},
        "convertHttpImage2Base64": {
            "type": "boolean",
            "description": "Whether HTTP reference images are converted to base64 first.",
        },
    },
    ["prompt"],
)

USER_PROMPT_INPUT_SCHEMA = {
    "oneOf": [
        _text("The natural-language prompt."),
        _STRUCTURED_USER_PROMPT,
    ]
}

_CONTEXT_DESCRIPTION = (
    "Additional facts, rules, constraints, or output requirements for this AI "
    "call. Overrides inherited aiContexts; an empty string disables inherited "
    "user context."
)

INSIGHT_OPTIONS_INPUT_SCHEMA = _schema(
    {
        "domIncluded": {"type": ["boolean", "string"]},
        "screenshotIncluded": {"type": "boolean"},
        "context": _text(_CONTEXT_DESCRIPTION),
    }
)

LOCATE_OPTIONS_INPUT_SCHEMA = _schema(
    {
        "context": _text(_CONTEXT_DESCRIPTION),
        "deepLocate": {"type": "boolean"},
        "deepThink": {"type": "boolean"},
        "cacheable": {"type": "boolean"},
        "xpath": {"type": "string"},
        "fileChooserAccept": {"type": ["string", "array"]},
    }
)

AI_ACT_OPTIONS_INPUT_SCHEMA = _schema(
    {
        "effort": {"type": "string", "enum": ["fast", "balance", "deepThink"]},
        "cacheable": {"type": "boolean"},
        "fileChooserAccept": {"type": ["string", "array"]},
        "fileChooserAllowedDir": {"type": "string"},
        "deepThink": {"type": ["boolean", "string"]},
        "deepLocate": {"type": "boolean"},
        "context": _text(_CONTEXT_DESCRIPTION),
    }
)

OBSERVE_INPUT_SCHEMA = _schema(
    {
        "act": USER_PROMPT_INPUT_SCHEMA,
        "assert": USER_PROMPT_INPUT_SCHEMA,
        "settleMs": {"type": "integer", "minimum": 0, "default": 0},
    },
    ["act", "assert"],
)

SET_AI_CONTEXT_INPUT_SCHEMA = _schema(
    {
        "target": {"type": "string"},
        "context": _text("Agent-level guidance."),
    },
    ["target"],
)

AI_ACT_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": AI_ACT_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

AI_ASSERT_OPTIONS_INPUT_SCHEMA = _schema(
    {
        **INSIGHT_OPTIONS_INPUT_SCHEMA["properties"],
        "keepRawResponse": {"type": "boolean"},
    }
)

AI_ASSERT_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "message": {"type": "string"},
        "options": AI_ASSERT_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

AI_TAP_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": LOCATE_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

AI_INPUT_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "value": {"type": ["string", "number"]},
        "options": _schema(
            {
                **LOCATE_OPTIONS_INPUT_SCHEMA["properties"],
                "mode": {"type": "string", "enum": ["replace", "clear", "typeOnly", "append"]},
                "autoDismissKeyboard": {"type": "boolean"},
                "keyboardTypeDelay": {"type": "number", "minimum": 0},
                "inputStrategy": {"type": "string"},
            }
        ),
    },
    ["prompt", "value"],
)

AI_KEYBOARD_PRESS_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "keyName": _text("The key or key combination to press."),
        "options": LOCATE_OPTIONS_INPUT_SCHEMA,
    },
    ["keyName"],
)

AI_SCROLL_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": _schema(
            {
                **LOCATE_OPTIONS_INPUT_SCHEMA["properties"],
                "direction": {"type": "string", "enum": ["down", "up", "right", "left"]},
                "scrollType": {
                    "type": "string",
                    "enum": [
                        "singleAction",
                        "scrollToBottom",
                        "scrollToTop",
                        "scrollToRight",
                        "scrollToLeft",
                        "once",
                        "untilBottom",
                        "untilTop",
                        "untilRight",
                        "untilLeft",
                    ],
                },
                "distance": {"type": ["number", "null"]},
            }
        ),
    }
)

AI_PINCH_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "direction": {"type": "string", "enum": ["in", "out"]},
        "options": _schema(
            {
                **LOCATE_OPTIONS_INPUT_SCHEMA["properties"],
                "distance": {"type": "number"},
                "duration": {"type": "number", "minimum": 0},
            }
        ),
    },
    ["direction"],
)

AI_LONG_PRESS_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": _schema(
            {
                **LOCATE_OPTIONS_INPUT_SCHEMA["properties"],
                "duration": {"type": "number", "minimum": 0},
            }
        ),
    },
    ["prompt"],
)

AI_DRAG_AND_DROP_INPUT_SCHEMA = _schema(
    {
        "from": USER_PROMPT_INPUT_SCHEMA,
        "to": USER_PROMPT_INPUT_SCHEMA,
        "options": LOCATE_OPTIONS_INPUT_SCHEMA,
    },
    ["from", "to"],
)

AI_QUERY_INPUT_SCHEMA = _schema(
    {
        "prompt": {"oneOf": [_text("The extraction request."), {"type": "object"}]},
        "options": INSIGHT_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

AI_WAIT_FOR_OPTIONS_INPUT_SCHEMA = _schema(
    {
        **INSIGHT_OPTIONS_INPUT_SCHEMA["properties"],
        "timeoutMs": {"type": "number", "exclusiveMinimum": 0},
        "checkIntervalMs": {"type": "number", "exclusiveMinimum": 0},
    }
)

AI_WAIT_FOR_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": AI_WAIT_FOR_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

JAVASCRIPT_INPUT_SCHEMA = _schema(
    {"script": _text("JavaScript to evaluate through the current interface.")},
    ["script"],
)

RUN_GHERKIN_SCENARIO_INPUT_SCHEMA = _schema(
    {
        "scenario": _text("The Gherkin scenario to execute."),
        "options": AI_ACT_OPTIONS_INPUT_SCHEMA,
    },
    ["scenario"],
)

ACTION_INPUT_SCHEMA = _schema(
    {
        "name": _text("The ActionSpace action name, for example DragAndDrop."),
        "params": {},
    },
    ["name"],
)

INSIGHT_INPUT_SCHEMA = _schema(
    {
        "prompt": USER_PROMPT_INPUT_SCHEMA,
        "options": INSIGHT_OPTIONS_INPUT_SCHEMA,
    },
    ["prompt"],
)

REPORT_SCREENSHOT_INPUT_SCHEMA = _schema(
    {
        "base64": _text("A base64-encoded screenshot."),
        "description": _text("What the screenshot shows."),
    },
    ["base64"],
)

RECORD_TO_REPORT_OPTIONS_INPUT_SCHEMA = _schema(
    {
        "content": _text("The report text content."),
        "screenshotBase64": _text("One base64-encoded screenshot."),
        "screenshots": {
            "type": "array",
            "items": REPORT_SCREENSHOT_INPUT_SCHEMA,
            "minItems": 1,
        },
    }
)

RECORD_TO_REPORT_INPUT_SCHEMA = _schema(
    {
        "title": _text("The report section title."),
        "options": RECORD_TO_REPORT_OPTIONS_INPUT_SCHEMA,
    }
)


def _define_common_agent_node(agent_label: str = "an Agent"):
    return create_agent_test_runner_node_definition(agent_label)


def _prompt_text(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        value = prompt.get("prompt")
        return value if isinstance(value, str) else ""
    return ""


def _build_locate_param(prompt: Any, options: Optional[Dict[str, Any]]) -> Any:
    # Imported lazily: the YAML package imports this module during its own init.
    from midscene.core.yaml.utils import build_detailed_locate_param

    return build_detailed_locate_param(prompt, options)


def _value_result(
    value: Any, _input_value: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {"data": value}


_define_common = _define_common_agent_node()
_define_action = _define_common_agent_node()

_AI_ACT_NODE = _define_common(
    {
        "method": "ai_act",
        "name": "aiAct",
        "description": "Perform a natural-language task with a Midscene UI Agent.",
        "string_input_key": "prompt",
        "input_schema": AI_ACT_INPUT_SCHEMA,
        "to_args": lambda input_value, context: [
            input_value.get("prompt"),
            {**(input_value.get("options") or {}), "abortSignal": context.signal},
        ],
        "to_result": lambda output, input_value: (
            None
            if output is None
            else {"summary": output if isinstance(output, str) else str(output)}
        ),
    }
)

_AI_TAP_NODE = _define_common(
    {
        "method": "ai_tap",
        "name": "aiTap",
        "description": "Locate and tap an element with a Midscene UI Agent.",
        "string_input_key": "prompt",
        "input_schema": AI_TAP_INPUT_SCHEMA,
        "to_args": lambda input_value, context: [
            input_value.get("prompt"),
            input_value.get("options"),
        ],
        "to_result": lambda _output, input_value: {
            "summary": f"Tapped: {_prompt_text(input_value.get('prompt'))}"
        },
    }
)

def _ai_assert_result(output: Any, input_value: Dict[str, Any]) -> Dict[str, Any]:
    text = _prompt_text(input_value.get("prompt"))
    result: Dict[str, Any] = {
        "summary": (
            "Assertion "
            f"{'failed' if isinstance(output, dict) and output.get('pass') is False else 'passed'}: "
            f"{text}"
        )
    }
    if isinstance(output, dict):
        data = {"pass": output.get("pass")}
        if output.get("thought") is not None:
            data["thought"] = output["thought"]
        if output.get("message") is not None:
            data["message"] = output["message"]
        result["data"] = data
    if isinstance(output, dict) and output.get("pass") is False:
        message = (
            output.get("message")
            or input_value.get("message")
            or output.get("thought")
            or f"Assertion failed: {text}"
        )
        raise NodeExecutionError("aiAssert", Exception(message), result)
    return result


_AI_ASSERT_NODE = _define_common(
    {
        "method": "ai_assert",
        "name": "aiAssert",
        "description": "Assert a natural-language condition with a Midscene UI Agent.",
        "string_input_key": "prompt",
        "input_schema": AI_ASSERT_INPUT_SCHEMA,
        "to_args": lambda input_value, context: [
            input_value.get("prompt"),
            input_value.get("message"),
            {
                "keepRawResponse": True,
                **(input_value.get("options") or {}),
                "abortSignal": context.signal,
            },
        ],
        "to_result": _ai_assert_result,
    }
)


def _locate_action_node(method: str, name: str, description: str) -> AgentTestRunnerNodeDefinition:
    return _define_action(
        {
            "method": method,
            "name": name,
            "description": description,
            "string_input_key": "prompt",
            "input_schema": AI_TAP_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                input_value.get("options"),
            ],
            "to_result": lambda _output, input_value: {
                "summary": f"{name}: {_prompt_text(input_value.get('prompt'))}"
            },
        }
    )


_ADDITIONAL_AGENT_NODES: List[AgentTestRunnerNodeDefinition] = [
    _define_action(
        {
            "method": "set_ai_context",
            "name": "setAIContext",
            "description": (
                "Set or remove Agent-level AI guidance for subsequent calls on "
                "the same Agent."
            ),
            "input_schema": SET_AI_CONTEXT_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("target"),
                input_value.get("context"),
            ],
        }
    ),
    _locate_action_node(
        "ai_hover", "aiHover", "Locate and hover over an element with a Midscene UI Agent."
    ),
    _locate_action_node(
        "ai_double_click",
        "aiDoubleClick",
        "Locate and double-click an element with a Midscene UI Agent.",
    ),
    _locate_action_node(
        "ai_right_click",
        "aiRightClick",
        "Locate and right-click an element with a Midscene UI Agent.",
    ),
    _locate_action_node(
        "ai_middle_click",
        "aiMiddleClick",
        "Locate and middle-click an element with a Midscene UI Agent.",
    ),
    _locate_action_node(
        "ai_clear_input",
        "aiClearInput",
        "Locate an input element and clear its value with a Midscene UI Agent.",
    ),
    _define_action(
        {
            "method": "ai_input",
            "name": "aiInput",
            "description": (
                "Locate an input element and enter a value with a Midscene UI Agent."
            ),
            "input_schema": AI_INPUT_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {**(input_value.get("options") or {}), "value": input_value.get("value")},
            ],
        }
    ),
    _define_action(
        {
            "method": "ai_keyboard_press",
            "name": "aiKeyboardPress",
            "description": (
                "Press a key or key combination, optionally targeting a located "
                "element."
            ),
            "string_input_key": "keyName",
            "input_schema": AI_KEYBOARD_PRESS_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {
                    **(input_value.get("options") or {}),
                    "keyName": input_value.get("keyName"),
                },
            ],
        }
    ),
    _define_action(
        {
            "method": "ai_scroll",
            "name": "aiScroll",
            "description": "Scroll the page or a located region with a Midscene UI Agent.",
            "string_input_key": "prompt",
            "input_schema": AI_SCROLL_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                dict(input_value.get("options") or {}),
            ],
        }
    ),
    _define_action(
        {
            "method": "ai_pinch",
            "name": "aiPinch",
            "description": (
                "Perform a pinch-in or pinch-out gesture with a Midscene UI Agent."
            ),
            "input_schema": AI_PINCH_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {
                    **(input_value.get("options") or {}),
                    "direction": input_value.get("direction"),
                },
            ],
        }
    ),
    _define_action(
        {
            "method": "ai_long_press",
            "name": "aiLongPress",
            "description": "Locate and long-press an element with a Midscene UI Agent.",
            "string_input_key": "prompt",
            "input_schema": AI_LONG_PRESS_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                input_value.get("options"),
            ],
        }
    ),
    _define_action(
        {
            "method": "_call_action_in_action_space",
            "name": "aiDragAndDrop",
            "description": (
                "Locate source and destination elements, then drag the source to "
                "the destination."
            ),
            "input_schema": AI_DRAG_AND_DROP_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                "DragAndDrop",
                {
                    "from": _build_locate_param(input_value.get("from"), input_value.get("options")),
                    "to": _build_locate_param(input_value.get("to"), input_value.get("options")),
                },
            ],
        }
    ),
    _define_action(
        {
            "method": "ai_locate",
            "name": "aiLocate",
            "description": (
                "Locate an element from a natural-language description and store "
                "the result."
            ),
            "string_input_key": "prompt",
            "input_schema": AI_TAP_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {**(input_value.get("options") or {}), "abortSignal": context.signal},
            ],
            "to_result": _value_result,
        }
    ),
    _define_action(
        {
            "method": "ai_query",
            "name": "aiQuery",
            "description": (
                "Extract structured data from the current interface and store "
                "the result."
            ),
            "string_input_key": "prompt",
            "input_schema": AI_QUERY_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {**(input_value.get("options") or {}), "abortSignal": context.signal},
            ],
            "to_result": _value_result,
        }
    ),
    _define_action(
        {
            "method": "ai_wait_for",
            "name": "aiWaitFor",
            "description": "Wait until a natural-language condition is satisfied.",
            "string_input_key": "prompt",
            "input_schema": AI_WAIT_FOR_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {**(input_value.get("options") or {}), "abortSignal": context.signal},
            ],
        }
    ),
    _define_action(
        {
            "method": "evaluate_javascript",
            "name": "javascript",
            "description": (
                "Evaluate JavaScript in the current interface and store the result."
            ),
            "string_input_key": "script",
            "input_schema": JAVASCRIPT_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [input_value.get("script")],
            "to_result": _value_result,
        }
    ),
    _define_action(
        {
            "method": "run_gherkin_scenario",
            "name": "runGherkinScenario",
            "description": "Execute a Gherkin scenario with the current Midscene UI Agent.",
            "string_input_key": "scenario",
            "input_schema": RUN_GHERKIN_SCENARIO_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("scenario"),
                {**(input_value.get("options") or {}), "abortSignal": context.signal},
            ],
        }
    ),
    _define_action(
        {
            "method": "_call_action_in_action_space",
            "name": "action",
            "description": (
                "Call a platform or custom action. Its ActionSpace schema "
                "validates params when the action executes."
            ),
            "input_schema": ACTION_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("name"),
                input_value.get("params"),
            ],
            "to_result": lambda value, input_value: (
                None if value is None else _value_result(value)
            ),
        }
    ),
]


def _insight_node(method: str, name: str) -> AgentTestRunnerNodeDefinition:
    def to_result(value: Any, input_value: Dict[str, Any]) -> Dict[str, Any]:
        summary_value = (
            json.dumps(value, ensure_ascii=False)
            if name in ("aiString", "aiAsk")
            else value
        )
        return {
            "summary": f"{name} returned {summary_value}",
            "data": {"value": value},
        }

    return _define_common(
        {
            "method": method,
            "name": name,
            "description": (
                f"Run {name} with a Midscene UI Agent and store its value."
            ),
            "string_input_key": "prompt",
            "input_schema": INSIGHT_INPUT_SCHEMA,
            "to_args": lambda input_value, context: [
                input_value.get("prompt"),
                {**(input_value.get("options") or {}), "abortSignal": context.signal},
            ],
            "to_result": to_result,
        }
    )


_RECORD_TO_REPORT_NODE = _define_common(
    {
        "method": "record_to_report",
        "name": "recordToReport",
        "description": "Add text or screenshots to the current Midscene report.",
        "string_input_key": "title",
        "input_schema": RECORD_TO_REPORT_INPUT_SCHEMA,
        "to_args": lambda input_value, context: [
            input_value.get("title"),
            input_value.get("options"),
        ],
        "to_result": lambda _output, input_value: {
            "summary": (
                f"Recorded to report: {input_value.get('title') or 'untitled'}"
            )
        },
    }
)


async def _execute_observe_node(
    agent: Any,
    input_value: Dict[str, Any],
    context: AgentTestRunnerNodeExecutionContext,
) -> Any:
    parsed = dict(input_value)
    parsed.setdefault("settleMs", 0)
    return await execute_observe(agent, parsed, context.signal)


def _sleep_node() -> AgentTestRunnerNodeDefinition:
    def to_args(input_value: Dict[str, Any], context: AgentTestRunnerNodeExecutionContext):
        signal = context.signal
        if signal is not None and getattr(signal, "aborted", False):
            signal.throw_if_aborted()
        return [input_value.get("ms"), {"abortSignal": signal}]

    return _define_action(
        {
            "method": "sleep",
            "name": "sleep",
            "description": (
                "Wait for a fixed number of milliseconds, recording standard UI "
                "snapshots and honoring cancellation."
            ),
            "input_schema": _schema(
                {"ms": {"type": "number", "exclusiveMinimum": 0}}, ["ms"]
            ),
            "to_args": to_args,
        }
    )


COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS: List[AgentTestRunnerNodeDefinition] = [
    _sleep_node(),
    AgentTestRunnerNodeDefinition(
        name="observe",
        description=(
            "Observe one AI action and assert against its screenshot sequence, "
            "including transient states."
        ),
        string_input_key=False,
        input_schema=OBSERVE_INPUT_SCHEMA,
        execute=_execute_observe_node,
    ),
    _AI_ACT_NODE,
    _AI_TAP_NODE,
    _AI_ASSERT_NODE,
    _insight_node("ai_boolean", "aiBoolean"),
    _insight_node("ai_number", "aiNumber"),
    _insight_node("ai_string", "aiString"),
    _insight_node("ai_ask", "aiAsk"),
    _RECORD_TO_REPORT_NODE,
    *_ADDITIONAL_AGENT_NODES,
]


__all__ = [
    "AI_ACT_INPUT_SCHEMA",
    "AI_ASSERT_INPUT_SCHEMA",
    "AI_DRAG_AND_DROP_INPUT_SCHEMA",
    "AI_INPUT_INPUT_SCHEMA",
    "AI_KEYBOARD_PRESS_INPUT_SCHEMA",
    "AI_LONG_PRESS_INPUT_SCHEMA",
    "AI_PINCH_INPUT_SCHEMA",
    "AI_QUERY_INPUT_SCHEMA",
    "AI_SCROLL_INPUT_SCHEMA",
    "AI_TAP_INPUT_SCHEMA",
    "AI_WAIT_FOR_INPUT_SCHEMA",
    "ACTION_INPUT_SCHEMA",
    "AgentTestRunnerNodeDefinition",
    "AgentTestRunnerNodeExecutionContext",
    "COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS",
    "INSIGHT_INPUT_SCHEMA",
    "INSIGHT_OPTIONS_INPUT_SCHEMA",
    "JAVASCRIPT_INPUT_SCHEMA",
    "LOCATE_OPTIONS_INPUT_SCHEMA",
    "OBSERVE_INPUT_SCHEMA",
    "RECORD_TO_REPORT_INPUT_SCHEMA",
    "RUN_GHERKIN_SCENARIO_INPUT_SCHEMA",
    "SET_AI_CONTEXT_INPUT_SCHEMA",
    "USER_PROMPT_INPUT_SCHEMA",
    "create_agent_test_runner_node_definition",
]
