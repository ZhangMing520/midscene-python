"""Generate tools from an action space and common CLI tools.

Port of upstream agent-tools/tool-generator.ts. Action schemas are plain dict
field descriptors instead of Zod objects.
"""

import inspect
import json
import sys
from typing import Any, Awaitable, Callable, Dict, List, Optional

from midscene.shared.agent_tools.error_formatter import get_error_message
from midscene.shared.agent_tools.observation_artifact import (
    resolve_observation_artifact_adapter,
)
from midscene.shared.agent_tools.observation_record import (
    read_ui_observation_record,
)
from midscene.shared.agent_tools.tool_defaults import ToolDefaults
from midscene.shared.agent_tools.types import (
    ActionSpaceItem,
    ToolCliMetadata,
    ToolDefinition,
    ToolResult,
    ToolSchema,
    schema_field,
)
from midscene.shared.agent_tools.user_prompt import (
    PROMPT_INPUT_EXTRA_SCHEMA,
    compose_user_prompt,
)
from midscene.shared.cli.verbose import (
    attach_cli_verbose_dump_listener,
    emit_cli_verbose_event,
)
from midscene.shared.img import parse_base64
from midscene.shared.key_alias_utils import is_record

GetAgent = Callable[[Dict[str, Any]], Awaitable[Any]]


def _action_attr(action: Any, name: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        return action.get(name, default)
    return getattr(action, name, default)


def _field_types(field: Dict[str, Any]) -> List[str]:
    raw = field.get("type", "any")
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [part.strip() for part in str(raw).split("|")]


def _get_field_shape(field: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(field, dict):
        return None
    fields = field.get("fields")
    if isinstance(fields, dict):
        return fields
    shape = field.get("shape")
    if isinstance(shape, dict):
        return shape
    if field.get("type") == "locate":
        return {"prompt": schema_field("string")}
    return None


def _is_midscene_locator_field(field: Any) -> bool:
    if not isinstance(field, dict):
        return False
    if field.get("type") == "locate":
        return True
    shape = _get_field_shape(field)
    return bool(shape and "prompt" in shape)


def _is_optional(field: Dict[str, Any]) -> bool:
    return bool(field.get("optional", False))


def _type_name_for_display(field: Dict[str, Any]) -> str:
    if _is_midscene_locator_field(field):
        return "object"
    return " | ".join(_field_types(field))


def _describe_action_for_tool(action: Any) -> str:
    name = _action_attr(action, "name", "")
    description = _action_attr(action, "description") or f"Execute {name} action"
    param_schema: Dict[str, Any] = _action_attr(action, "param_schema", None) or {}

    if not param_schema:
        return f"{name} action, {description}"

    param_descriptions: List[str] = []
    for key, field in param_schema.items():
        if not isinstance(field, dict):
            continue
        type_name = _type_name_for_display(field)
        description_text = field.get("description") or ""
        if not description_text and _is_midscene_locator_field(field):
            description_text = "Location information for the target element"
        param_text = f"{key}{'?' if _is_optional(field) else ''} ({type_name})"
        if description_text:
            param_text += f" - {description_text}"
        param_descriptions.append(param_text)

    if not param_descriptions:
        return f"{name} action, {description}"
    return (
        f"{name} action, {description}. Parameters: "
        f"{'; '.join(param_descriptions)}"
    )


def _transform_schema_field(
    key: str, value: Dict[str, Any]
) -> Dict[str, Any]:
    if not _is_midscene_locator_field(value):
        return value
    shape = _get_field_shape(value)
    if not shape:
        return value
    if value.get("type") == "locate" and "fields" not in value:
        return value
    new_shape = dict(shape)
    new_shape["prompt"] = {**shape["prompt"], "optional": True}
    return {**value, "type": "object", "fields": new_shape}


def _extract_action_schema(
    param_schema: Optional[Dict[str, Any]], action_name: str
) -> Dict[str, Any]:
    if not param_schema:
        return {}
    if not isinstance(param_schema, dict):
        raise ValueError(
            f'Action "{action_name}" declared a non-object param_schema '
            f"({type(param_schema).__name__}). CLI tool schemas must be a dict "
            "of field descriptors or undefined."
        )
    return {
        key: _transform_schema_field(key, value)
        for key, value in param_schema.items()
        if isinstance(value, dict)
    }


def _get_prompt_text(prompt: Any) -> Optional[str]:
    if isinstance(prompt, str):
        return prompt
    if is_record(prompt) and isinstance(prompt.get("prompt"), str):
        return prompt["prompt"]
    return None


def _move_locate_extras_into_prompt(
    value: Dict[str, Any], locate_field_keys: set
) -> Dict[str, Any]:
    prompt_text = _get_prompt_text(value.get("prompt"))
    if not prompt_text:
        return value

    normalized_prompt: Dict[str, Any] = (
        dict(value["prompt"]) if is_record(value.get("prompt")) else {"prompt": prompt_text}
    )
    normalized_locate: Dict[str, Any] = {}
    moved_extra_field = False

    for key, field_value in value.items():
        if key == "prompt":
            continue
        if key in locate_field_keys:
            normalized_locate[key] = field_value
            continue
        moved_extra_field = True
        if key not in normalized_prompt:
            normalized_prompt[key] = field_value

    if not moved_extra_field:
        return value
    return {**normalized_locate, "prompt": normalized_prompt}


def _normalize_locate_like_arg(value: Any, field_schema: Any) -> Any:
    if isinstance(value, str):
        return {"prompt": value}
    if not is_record(value):
        return value
    shape = _get_field_shape(field_schema)
    if not shape:
        return value
    return _move_locate_extras_into_prompt(value, set(shape.keys()))


def _normalize_action_args(
    args: Dict[str, Any], param_schema: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    if not param_schema:
        return args
    return {
        key: (
            _normalize_locate_like_arg(value, param_schema.get(key))
            if key in param_schema
            and _is_midscene_locator_field(param_schema.get(key))
            else value
        )
        for key, value in args.items()
    }


def _merge_locate_defaults(
    locate: Dict[str, Any], defaults: Dict[str, Any]
) -> Dict[str, Any]:
    merged: Optional[Dict[str, Any]] = None
    for key, value in defaults.items():
        if locate.get(key) is not None:
            continue
        if key == "deepLocate" and locate.get("deepThink") is not None:
            continue
        merged = dict(locate) if merged is None else merged
        merged[key] = value
    return merged if merged is not None else locate


def _apply_locate_defaults(
    args: Dict[str, Any],
    param_schema: Optional[Dict[str, Any]],
    locate_defaults: Dict[str, Any],
) -> Dict[str, Any]:
    if not param_schema or not locate_defaults:
        return args
    result = dict(args)
    for key, value in args.items():
        field_schema = param_schema.get(key)
        if (
            field_schema is not None
            and _is_midscene_locator_field(field_schema)
            and is_record(value)
        ):
            result[key] = _merge_locate_defaults(value, locate_defaults)
    return result


def _serialize_args_to_description(args: Dict[str, Any]) -> str:
    try:
        parts = []
        for key, value in args.items():
            if isinstance(value, (dict, list)):
                try:
                    parts.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                except (TypeError, ValueError):
                    parts.append(f"{key}: [object]")
            else:
                parts.append(f'{key}: "{value}"')
        return ", ".join(parts)
    except Exception as error:  # noqa: BLE001
        print(f"Error serializing args: {get_error_message(error)}", file=sys.stderr)
        return f"[args serialization failed: {get_error_message(error)}]"


def _build_action_instruction(
    action_name: str, args: Dict[str, Any]
) -> str:
    locate_prompt = (
        _get_prompt_text(args["locate"].get("prompt"))
        if is_record(args.get("locate"))
        else None
    )

    if action_name == "Tap":
        return f'Tap on "{locate_prompt}"' if locate_prompt else "Tap"
    if action_name == "Input":
        value = args.get("value") or args.get("content") or ""
        return (
            f'Input "{value}" into "{locate_prompt}"'
            if locate_prompt
            else f'Input "{value}"'
        )
    if action_name == "Scroll":
        direction = args.get("direction") or "down"
        return (
            f'Scroll {direction} on "{locate_prompt}"'
            if locate_prompt
            else f"Scroll {direction}"
        )
    if action_name == "Hover":
        return f'Hover over "{locate_prompt}"' if locate_prompt else "Hover"
    if action_name == "KeyboardPress":
        key = args.get("value") or args.get("key") or ""
        return f'Press key "{key}"'

    args_description = _serialize_args_to_description(args)
    return f"{action_name}: {args_description}" if args_description else action_name


async def _call_ai_action(
    agent: Any, prompt: Any, options: Optional[Dict[str, Any]] = None
) -> Any:
    options = options or {}
    method = getattr(agent, "ai_action", None) or getattr(agent, "aiAction", None)
    if method is None:
        raise RuntimeError("act is not supported by this agent")
    signature = inspect.signature(method)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return await method(prompt, **options)
    return await method(prompt, options)


async def _execute_action(
    agent: Any, action_name: str, args: Dict[str, Any]
) -> Any:
    call = (
        getattr(agent, "call_action_in_action_space", None)
        or getattr(agent, "callActionInActionSpace", None)
        or getattr(agent, "_call_action_in_action_space", None)
    )
    if call is not None:
        return await call(action_name, args)
    if getattr(agent, "ai_action", None) is not None:
        return await _call_ai_action(agent, _build_action_instruction(action_name, args))
    raise RuntimeError(f'Action "{action_name}" is not supported by this agent')


async def _screenshot_base64(agent: Any) -> Optional[str]:
    page = getattr(agent, "page", None)
    if page is not None and hasattr(page, "screenshot_base64"):
        value = page.screenshot_base64()
        return await value if inspect.isawaitable(value) else value
    get_context = getattr(agent, "get_ui_context", None)
    if get_context is not None:
        context = get_context("screenshot")
        if inspect.isawaitable(context):
            context = await context
        return getattr(context, "screenshot_base64", None)
    return None


async def _record_screenshot(agent: Any, screenshot: str) -> None:
    record = getattr(agent, "record_to_report", None)
    if record is None:
        return
    result = record("take_screenshot", {"screenshotBase64": screenshot})
    if inspect.isawaitable(result):
        await result


def _serialize_action_result(action_result: Any) -> str:
    if isinstance(action_result, str):
        return action_result
    try:
        return json.dumps(action_result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(action_result)


async def _capture_screenshot_result(
    agent: Any, action_name: str, action_result: Any = None
) -> ToolResult:
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f'Action "{action_name}" completed.'}
    ]
    if action_result is not None:
        content.append(
            {
                "type": "text",
                "text": f"Result: {_serialize_action_result(action_result)}",
            }
        )

    try:
        screenshot = await _screenshot_base64(agent)
        if not screenshot:
            return ToolResult(content)
        parsed = parse_base64(screenshot)
        content.append(
            {
                "type": "image",
                "data": parsed["body"],
                "mimeType": parsed["mimeType"],
            }
        )
        return ToolResult(content)
    except Exception as error:  # noqa: BLE001
        message = get_error_message(error)
        print(f"Error capturing screenshot: {message}", file=sys.stderr)
        content[0] = {
            "type": "text",
            "text": (
                f'Action "{action_name}" completed '
                f"(screenshot unavailable: {message})"
            ),
        }
        return ToolResult(content)


def _create_error_result(message: str) -> ToolResult:
    return ToolResult([{"type": "text", "text": message}], is_error=True)


async def _capture_failure_result(
    agent: Any, action_name: str, error_message: str
) -> ToolResult:
    warning = (
        f'Warning: Action "{action_name}" failed: {error_message}. Check the '
        "screenshot below for the current page state and decide how to proceed."
    )
    try:
        screenshot = await _screenshot_base64(agent)
        if not screenshot:
            return ToolResult([{"type": "text", "text": warning}])
        parsed = parse_base64(screenshot)
        return ToolResult(
            [
                {"type": "text", "text": warning},
                {
                    "type": "image",
                    "data": parsed["body"],
                    "mimeType": parsed["mimeType"],
                },
            ]
        )
    except Exception:  # noqa: BLE001
        return ToolResult([{"type": "text", "text": warning}])


def _merge_tool_cli_metadata(
    base: Optional[ToolCliMetadata], extra: Optional[ToolCliMetadata]
) -> Optional[ToolCliMetadata]:
    options = {**(base or {}).get("options", {}), **(extra or {}).get("options", {})}
    positionals = (base or {}).get("positionals") or (extra or {}).get("positionals")
    if options or positionals:
        result: ToolCliMetadata = {"options": options}
        if positionals:
            result["positionals"] = positionals
        return result
    return None


def generate_tools_from_action_space(
    action_space: List[ActionSpaceItem],
    get_agent: GetAgent,
    sanitize_args: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    init_arg_schema: Optional[ToolSchema] = None,
    init_arg_cli_metadata: Optional[ToolCliMetadata] = None,
    tool_defaults: Optional[ToolDefaults] = None,
) -> List[ToolDefinition]:
    """Convert DeviceActions from an action space into tool definitions."""
    sanitize = sanitize_args or (lambda args: args)
    init_schema = init_arg_schema or {}
    defaults = tool_defaults or {}

    definitions: List[ToolDefinition] = []
    for action in action_space:
        name = _action_attr(action, "name", "")
        param_schema = _action_attr(action, "param_schema", None) or {}
        schema = {
            **_extract_action_schema(param_schema, name),
            **init_schema,
        }

        async def handler(
            args: Dict[str, Any],
            action_name: str = name,
            action_param_schema: Dict[str, Any] = param_schema,
        ) -> ToolResult:
            try:
                agent = await get_agent(args)
                emit_cli_verbose_event(
                    {"event": "agent_ready", "tool": action_name}
                )
                unsubscribe = attach_cli_verbose_dump_listener(
                    agent, {"toolName": action_name}
                )
                try:
                    normalized_args = _normalize_action_args(
                        sanitize(dict(args)), action_param_schema
                    )
                    if defaults.get("locate"):
                        normalized_args = _apply_locate_defaults(
                            normalized_args,
                            action_param_schema,
                            defaults["locate"],
                        )
                    try:
                        action_result = await _execute_action(
                            agent, action_name, normalized_args
                        )
                    except Exception as error:  # noqa: BLE001
                        message = get_error_message(error)
                        print(
                            f'Error executing action "{action_name}": {message}',
                            file=sys.stderr,
                        )
                        return await _capture_failure_result(
                            agent, action_name, message
                        )
                    return await _capture_screenshot_result(
                        agent, action_name, action_result
                    )
                finally:
                    unsubscribe()
            except Exception as error:  # noqa: BLE001
                message = get_error_message(error)
                print(
                    f'Error in handler for "{action_name}": {message}',
                    file=sys.stderr,
                )
                return _create_error_result(
                    f'Failed to get agent or execute action "{action_name}": '
                    f"{message}"
                )

        definitions.append(
            ToolDefinition(
                name=name,
                description=_describe_action_for_tool(action),
                schema=schema,
                handler=handler,
                cli=init_arg_cli_metadata,
            )
        )
    return definitions


def generate_common_tools(
    get_agent: GetAgent,
    init_arg_schema: Optional[ToolSchema] = None,
    init_arg_cli_metadata: Optional[ToolCliMetadata] = None,
    tool_defaults: Optional[ToolDefaults] = None,
) -> List[ToolDefinition]:
    init_schema = init_arg_schema or {}
    defaults = tool_defaults or {}

    async def take_screenshot(args: Dict[str, Any]) -> ToolResult:
        try:
            agent = await get_agent(args)
            emit_cli_verbose_event(
                {"event": "agent_ready", "tool": "take_screenshot"}
            )
            unsubscribe = attach_cli_verbose_dump_listener(
                agent, {"toolName": "take_screenshot"}
            )
            try:
                screenshot = await _screenshot_base64(agent)
                if not screenshot:
                    return _create_error_result("Screenshot not available")
                await _record_screenshot(agent, screenshot)
                parsed = parse_base64(screenshot)
                return ToolResult(
                    [
                        {
                            "type": "image",
                            "data": parsed["body"],
                            "mimeType": parsed["mimeType"],
                        }
                    ]
                )
            finally:
                unsubscribe()
        except Exception as error:  # noqa: BLE001
            message = get_error_message(error)
            print(f"Error taking screenshot: {message}", file=sys.stderr)
            return _create_error_result(
                f"Failed to capture screenshot: {message}"
            )

    async def act(args: Dict[str, Any]) -> ToolResult:
        prompt = args.get("prompt")
        try:
            agent = await get_agent(args)
            emit_cli_verbose_event({"event": "agent_ready", "tool": "act"})
            if getattr(agent, "ai_action", None) is None and getattr(
                agent, "aiAction", None
            ) is None:
                return _create_error_result("act is not supported by this agent")
            unsubscribe = attach_cli_verbose_dump_listener(
                agent, {"toolName": "act"}
            )
            try:
                act_options: Dict[str, Any] = {
                    "deepThink": False,
                    **(defaults.get("act") or {}),
                }
                for key in (
                    "deepLocate",
                    "deepThink",
                    "fileChooserAllowedDir",
                ):
                    if args.get(key) is not None:
                        act_options[key] = args[key]
                user_prompt = compose_user_prompt(
                    prompt,
                    args.get("image"),
                    args.get("imageName"),
                    args.get("convertHttpImage2Base64"),
                )
                result = await _call_ai_action(agent, user_prompt, act_options)
                return await _capture_screenshot_result(agent, "act", result)
            finally:
                unsubscribe()
        except Exception as error:  # noqa: BLE001
            message = get_error_message(error)
            print(f"Error executing act: {message}", file=sys.stderr)
            return _create_error_result(f"Failed to execute act: {message}")

    async def assert_statement(args: Dict[str, Any]) -> ToolResult:
        prompt = args.get("prompt")
        message = args.get("message")
        try:
            agent = await get_agent(args)
            emit_cli_verbose_event({"event": "agent_ready", "tool": "assert"})
            if getattr(agent, "ai_assert", None) is None and getattr(
                agent, "aiAssert", None
            ) is None:
                return _create_error_result(
                    "assert is not supported by this agent"
                )
            unsubscribe = attach_cli_verbose_dump_listener(
                agent, {"toolName": "assert"}
            )
            try:
                record_path = args.get("record")
                observation_record = (
                    read_ui_observation_record(record_path)
                    if isinstance(record_path, str)
                    else None
                )
                user_prompt = compose_user_prompt(
                    prompt,
                    args.get("image"),
                    args.get("imageName"),
                    args.get("convertHttpImage2Base64"),
                )
                if observation_record:
                    adapter = resolve_observation_artifact_adapter(agent)
                    if adapter is None:
                        raise RuntimeError(
                            "assert --record is not supported because this "
                            "agent cannot load UI observations"
                        )
                    observation = adapter.load_record(observation_record)
                    try:
                        result = observation.ai_assert(user_prompt, message)
                        if inspect.isawaitable(result):
                            await result
                    finally:
                        dispose = getattr(observation, "dispose", None)
                        if dispose is not None:
                            disposed = dispose()
                            if inspect.isawaitable(disposed):
                                await disposed
                else:
                    ai_assert = getattr(agent, "ai_assert", None) or getattr(
                        agent, "aiAssert"
                    )
                    result = ai_assert(user_prompt, message)
                    if inspect.isawaitable(result):
                        await result
                return ToolResult(
                    [{"type": "text", "text": "Assertion passed."}]
                )
            finally:
                unsubscribe()
        except Exception as error:  # noqa: BLE001
            error_message = get_error_message(error)
            print(f"Error executing assert: {error_message}", file=sys.stderr)
            return _create_error_result(
                f"Failed to execute assert: {error_message}"
            )

    return [
        ToolDefinition(
            name="take_screenshot",
            description="Capture screenshot of current page/screen",
            schema={**init_schema},
            handler=take_screenshot,
            cli=init_arg_cli_metadata,
        ),
        ToolDefinition(
            name="act",
            description=(
                "Execute a natural language action. The AI will plan and "
                "perform multi-step operations in a single invocation, useful "
                "for transient UI interactions (e.g., Spotlight, dropdown "
                "menus) that disappear between separate commands."
            ),
            schema={
                "prompt": schema_field(
                    "string",
                    'Natural language description of the action to perform, '
                    'e.g. "press Command+Space, type Safari, press Enter"',
                ),
                "deepLocate": schema_field(
                    "boolean",
                    "Use deep locate for every element this action targets. "
                    "Improves precision for small or ambiguous targets at the "
                    "cost of speed. Defaults to the server --deep-locate "
                    "setting.",
                    optional=True,
                ),
                "deepThink": schema_field(
                    "boolean",
                    "Plan this action with deep thinking (richer context and "
                    "sub-goal decomposition). Helps with complex multi-step "
                    "instructions at the cost of speed. Defaults to the server "
                    "--deep-think setting.",
                    optional=True,
                ),
                "fileChooserAllowedDir": schema_field(
                    "string",
                    "Directory that model-planned file uploads may access. "
                    "Required when the prompt asks the model to upload files.",
                    optional=True,
                ),
                **PROMPT_INPUT_EXTRA_SCHEMA,
                **init_schema,
            },
            handler=act,
            cli=_merge_tool_cli_metadata(None, init_arg_cli_metadata),
        ),
        ToolDefinition(
            name="assert",
            description=(
                "Assert a natural language statement against the current "
                "page/screen or a saved UI observation record."
            ),
            schema={
                "prompt": schema_field(
                    "string",
                    'Natural language assertion to verify, e.g. "there is a '
                    'login button visible"',
                ),
                "message": schema_field(
                    "string",
                    "Custom error message to throw when the assertion fails, "
                    'e.g. "the login button should be visible".',
                    optional=True,
                ),
                "record": schema_field(
                    "string",
                    "Path to a JSON observation manifest created by the record "
                    "command. Keep its adjacent image directory with it. When "
                    "set, the assertion uses that ordered frame window instead "
                    "of the current screen.",
                    optional=True,
                ),
                **PROMPT_INPUT_EXTRA_SCHEMA,
                **init_schema,
            },
            handler=assert_statement,
            cli=_merge_tool_cli_metadata(None, init_arg_cli_metadata),
        ),
    ]


__all__ = [
    "generate_common_tools",
    "generate_tools_from_action_space",
]
