"""Foreground recording command (upstream cli/record-command.ts)."""

import inspect
from typing import Any, Awaitable, Callable, Dict, Optional

from midscene.shared.agent_tools.error_formatter import get_error_message
from midscene.shared.agent_tools.observation_artifact import (
    resolve_observation_artifact_adapter,
)
from midscene.shared.agent_tools.observation_record import (
    write_ui_observation_record,
)
from midscene.shared.agent_tools.types import (
    ToolCliMetadata,
    ToolDefinition,
    ToolResult,
    ToolSchema,
    schema_field,
)
from midscene.shared.cli.interrupt import create_cli_interrupt_waiter
from midscene.shared.cli.verbose import (
    attach_cli_verbose_dump_listener,
    emit_cli_verbose_event,
)

_RECORD_CLI_METADATA: ToolCliMetadata = {
    "positionals": ["action"],
    "options": {
        "intervalMs": {
            "preferredName": "interval-ms",
            "aliases": ["intervalMs"],
        },
        "maxFrames": {
            "preferredName": "max-frames",
            "aliases": ["maxFrames"],
        },
        "watchdogMs": {
            "preferredName": "watchdog-ms",
            "aliases": ["watchdogMs"],
        },
        "action": {"hidden": True},
    },
}


def _merge_cli_metadata(
    base: ToolCliMetadata, extra: Optional[ToolCliMetadata] = None
) -> ToolCliMetadata:
    return {
        "positionals": base.get("positionals"),
        "options": {
            **(base.get("options") or {}),
            **((extra or {}).get("options") or {}),
        },
    }


def _create_error_result(message: str) -> ToolResult:
    return ToolResult([{"type": "text", "text": message}], is_error=True)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def create_record_cli_command(
    get_agent: Callable[[Dict[str, Any]], Awaitable[Any]],
    init_arg_schema: Optional[ToolSchema] = None,
    init_arg_cli_metadata: Optional[ToolCliMetadata] = None,
) -> ToolDefinition:
    """Create the foreground recording command exposed only by Midscene CLIs."""
    init_schema = init_arg_schema or {}

    async def handler(args: Dict[str, Any]) -> ToolResult:
        if args.get("action") != "start":
            return _create_error_result(
                "record requires the start operation (for example: record start "
                "--output ./observation.json)"
            )

        try:
            agent = await get_agent(args)
            emit_cli_verbose_event({"event": "agent_ready", "tool": "record"})
            start_observing = getattr(agent, "start_observing", None)
            if start_observing is None:
                raise RuntimeError(
                    "record is not supported because this agent does not "
                    "provide startObserving"
                )
            observation_artifacts = resolve_observation_artifact_adapter(agent)
            if observation_artifacts is None:
                raise RuntimeError(
                    "record is not supported because this agent does not "
                    "provide observation artifact persistence"
                )
            unsubscribe_verbose = attach_cli_verbose_dump_listener(
                agent, {"toolName": "record"}
            )
            observer = None
            interrupt_waiter = None
            try:
                watchdog_ms = args.get("watchdogMs")
                if watchdog_ms is None:
                    watchdog_ms = 300_000
                observer = await _maybe_await(
                    start_observing(
                        {
                            "intervalMs": args.get("intervalMs"),
                            "maxFrames": args.get("maxFrames"),
                            "watchdogMs": watchdog_ms,
                        }
                    )
                )
                start = getattr(observer, "start", None)
                if start is not None:
                    await _maybe_await(start())
                interrupt_waiter = create_cli_interrupt_waiter(watchdog_ms)
                emit_cli_verbose_event(
                    {
                        "event": "recording_ready",
                        "tool": "record",
                        "watchdogMs": watchdog_ms,
                    }
                )
                stop_reason = await interrupt_waiter.result
                emit_cli_verbose_event(
                    {
                        "event": "recording_stopping",
                        "tool": "record",
                        "reason": stop_reason,
                    }
                )
                observation = await _maybe_await(observer.stop())
                record = await _maybe_await(
                    observation_artifacts.export_record(observation)
                )
                output_path = write_ui_observation_record(
                    record, args.get("output")
                )
                return ToolResult(
                    [
                        {
                            "type": "text",
                            "text": f"Observation record saved: {output_path}",
                        }
                    ]
                )
            finally:
                try:
                    if observer is not None:
                        dispose = getattr(observer, "dispose", None)
                        if dispose is not None:
                            await _maybe_await(dispose())
                finally:
                    if interrupt_waiter is not None:
                        interrupt_waiter.dispose()
                    unsubscribe_verbose()
        except Exception as error:  # noqa: BLE001
            error_message = get_error_message(error)
            print(f"Error executing record: {error_message}")
            return _create_error_result(
                f"Failed to execute record: {error_message}"
            )

    return ToolDefinition(
        name="record",
        description=(
            "Record the page/screen in the foreground until Ctrl+C or a "
            "termination signal, then save the ordered frame window for a "
            "later assert command."
        ),
        schema={
            "action": schema_field(
                "literal",
                "Start a foreground recording. Press Ctrl+C to finish.",
                value="start",
            ),
            "output": schema_field(
                "string",
                "Path for the JSON observation manifest. Frames are stored in "
                "an adjacent <name>.frames directory. Defaults to a generated "
                "path under midscene_run/output.",
                optional=True,
            ),
            "intervalMs": schema_field(
                "number",
                "Sampling interval in milliseconds. Defaults to 1000; minimum "
                "200 (5fps).",
                optional=True,
            ),
            "maxFrames": schema_field(
                "integer",
                "Maximum buffered frames. Defaults to 30; minimum 2.",
                optional=True,
            ),
            "watchdogMs": schema_field(
                "number",
                "Safety timeout in milliseconds. Defaults to 300000 (5 minutes); "
                "0 disables it.",
                optional=True,
            ),
            **init_schema,
        },
        handler=handler,
        cli=_merge_cli_metadata(_RECORD_CLI_METADATA, init_arg_cli_metadata),
    )


__all__ = ["create_record_cli_command"]
