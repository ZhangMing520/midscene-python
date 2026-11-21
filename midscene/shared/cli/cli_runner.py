"""Tools CLI runner (upstream cli/cli-runner.ts)."""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from midscene.shared.agent_tools.tool_defaults import (
    TOOL_BEHAVIOR_FLAGS,
    strip_behavior_flags,
)
from midscene.shared.agent_tools.types import ToolDefinition, ToolResult
from midscene.shared.cli.cli_args import (
    canonicalize_cli_arg_keys,
    format_cli_validation_error,
    get_cli_option_display,
    parse_cli_args,
)
from midscene.shared.cli.cli_error import CLIError
from midscene.shared.cli.screenshot_file import write_cli_screenshot_file
from midscene.shared.cli.verbose import (
    CLI_VERBOSE_FLAG,
    cli_verbose_error_message,
    compact_cli_verbose_args,
    emit_cli_verbose_event,
    strip_verbose_flag,
    with_cli_verbose_context,
)
from midscene.shared.logger import get_logger

debug = get_logger("cli-runner")


def _load_dotenv_from_cwd() -> None:
    """Load `.env` from the working directory before tool initialization."""
    path = Path(".env")
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _output_content_item(item: Dict[str, Any], is_error: bool) -> None:
    item_type = item.get("type")
    if item_type == "text":
        if is_error:
            print(item.get("text", ""), file=sys.stderr)
        else:
            print(item.get("text", ""))
        return
    if item_type == "image":
        filepath = write_cli_screenshot_file(
            item.get("data", ""),
            {
                "mimeType": item.get("mimeType"),
                "filenamePrefix": "screenshot",
            },
        )
        print(f"Screenshot saved: {filepath}")
        emit_cli_verbose_event(
            {
                "event": "artifact",
                "kind": "screenshot",
                "path": filepath,
                "mimeType": item.get("mimeType"),
            }
        )
        return
    print(f"[{item_type} content not displayed in CLI]")


def _output_result(result: ToolResult) -> None:
    for item in result.content:
        _output_content_item(item, bool(result.is_error))


def remove_prefix(name: str, prefix: Optional[str] = None) -> str:
    if prefix and name.startswith(prefix):
        return name[len(prefix) :]
    return name


def _get_global_options() -> List[Dict[str, str]]:
    return [
        {
            "flag": f"--{CLI_VERBOSE_FLAG}",
            "description": (
                "Print progress while the command is running. act and record "
                "print readable progress by default. Use --verbose=jsonl for "
                "structured events."
            ),
        },
        *[
            {"flag": f"--{flag['cli']}", "description": flag["description"]}
            for flag in TOOL_BEHAVIOR_FLAGS
        ],
    ]


def _print_global_options() -> None:
    options = _get_global_options()
    width = max(len(option["flag"]) for option in options)
    print("\nGlobal Options:")
    for option in options:
        print(f"  {option['flag']:<{width}} {option['description']}")


def _print_command_help(script_name: str, command: Dict[str, Any]) -> None:
    definition: ToolDefinition = command["def"]
    cli = definition.cli or {}
    positional_usage = " ".join(
        f"<{name}>" for name in (cli.get("positionals") or [])
    )
    suffix = f" {positional_usage}" if positional_usage else ""
    print(f"\nUsage: {script_name} {command['name']}{suffix} [options]\n")
    print(definition.description)

    global_flags = {option["flag"] for option in _get_global_options()}
    cli_options = cli.get("options") or {}
    positionals = cli.get("positionals") or []
    schema_entries = []
    for key, field in definition.schema.items():
        if key in positionals or (cli_options.get(key) or {}).get("hidden"):
            continue
        display = get_cli_option_display(key, cli_options.get(key))
        if display["label"] in global_flags:
            continue
        schema_entries.append((key, field))

    if schema_entries:
        width = max(
            22,
            *[
                len(get_cli_option_display(key, cli_options.get(key))["label"])
                for key, _ in schema_entries
            ],
        )
        print("\nOptions:")
        for key, field in schema_entries:
            display = get_cli_option_display(key, cli_options.get(key))
            description = field.get("description") or ""
            alias_text = (
                f" (aliases: {', '.join(display['aliases'])})"
                if display["aliases"]
                else ""
            )
            print(f"  {display['label']:<{width}} {description}{alias_text}")

    _print_global_options()


def _print_version(script_name: str, version: str) -> None:
    print(f"{script_name} v{version}")


def _print_help(
    script_name: str,
    commands: List[Dict[str, Any]],
    version: Optional[str] = None,
) -> None:
    if version:
        _print_version(script_name, version)
        print("")
    print(f"\nUsage: {script_name} <command> [options]\n")
    print("Commands:")
    for command in commands:
        if command.get("hidden"):
            continue
        print(f"  {command['name']:<30} {command['def'].description}")
    print(f"  {'version':<30} Show CLI version")
    _print_global_options()
    print(f'\nRun "{script_name} <command> --help" for more info.')


async def run_tools_cli(
    tools: Any,
    script_name: str,
    options: Optional[Dict[str, Any]] = None,
) -> None:
    options = options or {}
    input_args = options.get("argv")
    if input_args is None:
        input_args = sys.argv[1:]
    debug.info("CLI invoked: %s %s", script_name, " ".join(input_args))

    stripped = strip_verbose_flag(input_args)
    verbose = stripped["verbose"]
    verbose_format = stripped["format"]

    # Global behavior flags apply regardless of which command runs.
    raw_args, tool_defaults = strip_behavior_flags(stripped["rawArgs"])
    if tool_defaults and hasattr(tools, "set_tool_defaults"):
        tools.set_tool_defaults(tool_defaults)

    _load_dotenv_from_cwd()
    await tools.init_tools()

    tool_definitions = list(tools.get_tool_definitions())
    get_cli_tool_definitions = getattr(tools, "get_cli_tool_definitions", None)
    if get_cli_tool_definitions is not None:
        tool_definitions.extend(get_cli_tool_definitions())

    commands: List[Dict[str, Any]] = [
        {
            "name": remove_prefix(
                definition.name, options.get("stripPrefix")
            ).lower(),
            "def": definition,
        }
        for definition in tool_definitions
    ]
    for extra in options.get("extraCommands") or []:
        commands.append(
            {
                "name": extra["name"].lower(),
                "def": extra["def"],
                "hidden": extra.get("hidden"),
            }
        )
        for alias in extra.get("aliases") or []:
            commands.append(
                {"name": alias.lower(), "def": extra["def"], "hidden": True}
            )

    cli_version = options.get("version")
    command_name = raw_args[0] if raw_args else None
    rest_args = raw_args[1:]

    if not command_name or command_name in ("--help", "-h"):
        debug.info("showing help (no command or --help flag)")
        _print_help(script_name, commands, cli_version)
        return

    if command_name in ("--version", "-v") or command_name.lower() == "version":
        if not cli_version:
            raise CLIError("Failed to determine CLI version")
        _print_version(script_name, cli_version)
        return

    match = next(
        (
            command
            for command in commands
            if command["name"].lower() == command_name.lower()
        ),
        None,
    )
    if match is None:
        debug.info("unknown command: %s", command_name)
        print(f"Unknown command: {command_name}", file=sys.stderr)
        _print_help(script_name, commands, cli_version)
        raise CLIError(f"Unknown command: {command_name}")

    definition: ToolDefinition = match["def"]
    cli = definition.cli or {}
    positional_names = cli.get("positionals") or []
    positional_args: Dict[str, Any] = {}
    option_start_index = 0
    while (
        option_start_index < len(rest_args)
        and option_start_index < len(positional_names)
        and not rest_args[option_start_index].startswith("-")
    ):
        positional_args[positional_names[option_start_index]] = rest_args[
            option_start_index
        ]
        option_start_index += 1

    parsed_args = {
        **positional_args,
        **parse_cli_args(rest_args[option_start_index:], definition),
    }
    if parsed_args.get("help") is True:
        debug.info("showing command help for: %s", match["name"])
        _print_command_help(script_name, match)
        return

    cli_validation_error = format_cli_validation_error(
        script_name, match["name"], definition, parsed_args
    )
    if cli_validation_error:
        raise CLIError(cli_validation_error)

    handler_args = canonicalize_cli_arg_keys(
        script_name, match["name"], definition, parsed_args
    )

    debug.info("command: %s, args: %s", match["name"], handler_args)

    verbose_enabled = (
        verbose or match["name"] == "act" or match["name"] == "record"
    )

    async def run_command() -> None:
        started_at = time.time() * 1000
        emit_cli_verbose_event(
            {
                "event": "command_start",
                "args": compact_cli_verbose_args(handler_args),
            }
        )
        try:
            result = await definition.handler(handler_args)
            debug.info(
                "command %s completed, isError: %s",
                match["name"],
                bool(result.is_error),
            )
            _output_result(result)
            emit_cli_verbose_event(
                {
                    "event": "command_done",
                    "status": "error" if result.is_error else "ok",
                    "durationMs": time.time() * 1000 - started_at,
                }
            )
            if result.is_error:
                raise CLIError("Command failed", 1)
        except Exception as error:
            if not (
                isinstance(error, CLIError) and str(error) == "Command failed"
            ):
                emit_cli_verbose_event(
                    {
                        "event": "command_done",
                        "status": "error",
                        "durationMs": time.time() * 1000 - started_at,
                        "error": cli_verbose_error_message(error),
                    }
                )
            raise
        finally:
            await tools.destroy()

    await with_cli_verbose_context(
        {
            "enabled": verbose_enabled,
            "format": verbose_format,
            "scriptName": script_name,
            "commandName": match["name"],
            "startedAt": time.time() * 1000,
        },
        run_command,
    )


__all__ = ["run_tools_cli", "remove_prefix"]
