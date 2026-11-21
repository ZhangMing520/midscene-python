"""Legacy YAML Test Runner nodes (upstream yaml/test-runner-nodes.ts)."""

from typing import Any, Dict, List, Optional

from midscene.core.agent.test_runner_nodes import (
    AgentTestRunnerNodeDefinition,
    AgentTestRunnerNodeExecutionContext,
    COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
)
from midscene.core.test_runner.node.types import NodeResult
from midscene.core.yaml.test_runner_compat import compile_legacy_flow_item


async def _maybe_await(value: Any) -> Any:
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


def _schema(properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }


def _text(description: str) -> Dict[str, Any]:
    return {"type": "string", "description": description}


# Planning-only marker accepted by the old YAML grammar, not a native Test Node.
LEGACY_FINALIZE_NODE_DEFINITION = AgentTestRunnerNodeDefinition(
    name="Finalize",
    input_schema=_schema(),
    execute=lambda agent, input_value, context: None,
)


async def _execute_run_adb_shell(
    agent: Any, input_value: Dict[str, Any], context: AgentTestRunnerNodeExecutionContext
) -> Any:
    command = input_value.get("command")
    timeout = input_value.get("timeout")
    runner = getattr(agent, "run_adb_shell", None)
    if callable(runner):
        value = runner(command, timeout)
        import inspect

        if inspect.isawaitable(value):
            value = await value
    else:
        value = await agent._call_action_in_action_space(
            "RunAdbShell", {"command": command, "timeout": timeout}
        )
    return None if value is None else {"data": value}


LEGACY_RUN_ADB_SHELL_NODE_DEFINITION = AgentTestRunnerNodeDefinition(
    name="runAdbShell",
    input_schema=_schema(
        {
            "command": _text("The adb shell command."),
            "timeout": {"type": "number"},
        }
    ),
    execute=_execute_run_adb_shell,
)


async def _execute_legacy_action(
    agent: Any, input_value: Dict[str, Any], context: AgentTestRunnerNodeExecutionContext
) -> Any:
    context.signal.throw_if_aborted()
    action_space = await agent.get_action_space()
    context.signal.throw_if_aborted()
    flow = input_value.get("flow") or {}
    step = compile_legacy_flow_item(flow, action_space)
    if step["node"] == "legacyAction":
        raise AssertionError(f"unknown flowItem in yaml: {flow}")
    definition = _LEGACY_DEFINITIONS_BY_NAME.get(step["node"])
    if definition is None:
        raise AssertionError(f"Unknown Agent Node: {step['node']}")
    context.signal.throw_if_aborted()
    return await _maybe_await(definition.execute(agent, step["input"], context))


# Only YAML hosts resolve shorthand; the shared Agent receives canonical params.
LEGACY_ACTION_NODE_DEFINITION = AgentTestRunnerNodeDefinition(
    name="legacyAction",
    input_schema=_schema({"flow": {"type": "object"}}),
    execute=_execute_legacy_action,
)


def _execute_legacy_validation_error(
    agent: Any, input_value: Dict[str, Any], context: AgentTestRunnerNodeExecutionContext
) -> None:
    raise RuntimeError(input_value.get("message"))


# Preserve the old task failure phase without adding native parser controls.
LEGACY_VALIDATION_ERROR_NODE_DEFINITION = AgentTestRunnerNodeDefinition(
    name="legacyValidationError",
    input_schema=_schema({"message": _text("The failure message.")}),
    execute=_execute_legacy_validation_error,
)


# The old player checked YAML grammar, then passed options through to Agent.
# Validate only the compiled envelope here: native field whitelists, positive
# wait durations and nonempty image arrays must not narrow the legacy grammar.
# compile_legacy_flow_item preserves the old checks at their task execution
# phase; Agent/ActionSpace remain responsible for validating business params.
_LEGACY_PROMPT_INPUT_SCHEMA = _schema(
    {
        "prompt": {},
        "options": {"type": "object"},
    }
)
_LEGACY_INPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    name: _LEGACY_PROMPT_INPUT_SCHEMA
    for name in (
        "aiAct",
        "aiTap",
        "aiLocate",
        "aiQuery",
        "aiNumber",
        "aiString",
        "aiBoolean",
        "aiAsk",
        "aiWaitFor",
        "aiScroll",
    )
}
_LEGACY_INPUT_SCHEMAS["aiAssert"] = {
    **_LEGACY_PROMPT_INPUT_SCHEMA,
    "properties": {
        **_LEGACY_PROMPT_INPUT_SCHEMA["properties"],
        "message": {},
    },
}
_LEGACY_INPUT_SCHEMAS["javascript"] = _schema({"script": {}})
_LEGACY_INPUT_SCHEMAS["runGherkinScenario"] = _schema(
    {"scenario": {}, "options": {"type": "object"}}
)
_LEGACY_INPUT_SCHEMAS["sleep"] = _schema(
    {"ms": {"type": "number", "exclusiveMinimum": 0}}
)
_LEGACY_INPUT_SCHEMAS["action"] = _schema({"name": _text("The action name."), "params": {}})
_LEGACY_INPUT_SCHEMAS["recordToReport"] = _schema(
    {"title": {}, "options": {"type": "object"}}
)

_SHARED_DEFINITIONS: Dict[str, AgentTestRunnerNodeDefinition] = {
    definition.name: definition
    for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}

_LEGACY_DEFINITIONS: List[AgentTestRunnerNodeDefinition] = []
for _name, _input_schema in _LEGACY_INPUT_SCHEMAS.items():
    _shared = _SHARED_DEFINITIONS.get(_name)
    if _shared is None:
        raise AssertionError(f"Missing shared Agent Node for legacy YAML: {_name}")
    _LEGACY_DEFINITIONS.append(
        AgentTestRunnerNodeDefinition(
            name=_shared.name,
            execute=_shared.execute,
            title=_shared.title,
            description=_shared.description,
            string_input_key=_shared.string_input_key,
            input_schema=_input_schema,
        )
    )
_LEGACY_DEFINITIONS.extend(
    [
        LEGACY_FINALIZE_NODE_DEFINITION,
        LEGACY_RUN_ADB_SHELL_NODE_DEFINITION,
        LEGACY_ACTION_NODE_DEFINITION,
        LEGACY_VALIDATION_ERROR_NODE_DEFINITION,
    ]
)

LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS: List[AgentTestRunnerNodeDefinition] = (
    _LEGACY_DEFINITIONS
)

_LEGACY_DEFINITIONS_BY_NAME: Dict[str, AgentTestRunnerNodeDefinition] = {
    definition.name: definition
    for definition in LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}

_INSIGHT_NODES = {"aiBoolean", "aiNumber", "aiString", "aiAsk"}


def get_legacy_yaml_result_data(node: str, output: Any) -> Any:
    """Keep Test's `{ value }` contract; only the legacy view unwraps insights."""
    data = output.data if isinstance(output, NodeResult) else (output or {}).get("data")
    if node in _INSIGHT_NODES:
        return data.get("value") if isinstance(data, dict) else None
    return data


__all__ = [
    "LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS",
    "get_legacy_yaml_result_data",
]
