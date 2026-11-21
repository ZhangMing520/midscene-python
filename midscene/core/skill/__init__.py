"""Skill CLI over a custom Device class (upstream core/src/skill/index.ts).

The upstream module delegates to `@midscene/shared/cli`'s tools runner, which
is not ported. This Python counterpart keeps the same entry point: it lazily
creates an Agent from a Device class and serves newline-delimited JSON
commands on stdin, printing one JSON response per command.
"""

import asyncio
import json
import sys
from typing import Any, Dict, Optional, Type

from midscene.core.agent.agent import Agent


class SkillMidsceneTools:
    """Lazily create an Agent from a Device class for CLI / Agent Skills."""

    def __init__(self, device_class: Type[Any]) -> None:
        self._device_class = device_class
        self.agent: Optional[Agent] = None

    def create_temporary_device(self) -> Any:
        return self._device_class()

    async def ensure_agent(self) -> Agent:
        if self.agent is None:
            self.agent = Agent(self._device_class())
        return self.agent


def report_cli_error(error: BaseException) -> int:
    """Print a CLI error and return the process exit code."""
    print(f"Error: {error}", file=sys.stderr)
    return 1


async def _run_command(agent: Agent, command: str, args: Dict[str, Any]) -> Any:
    if command == "act":
        return await agent.ai_act(args.get("prompt"))
    if command == "assert":
        await agent.ai_assert(args.get("prompt"))
        return None
    if command == "query":
        return await agent.ai_query(args.get("prompt"))
    if command == "tap":
        await agent.ai_tap(args.get("prompt"))
        return None
    if command == "input":
        await agent.ai_input(args.get("prompt"), {"value": args.get("value")})
        return None
    if command == "sleep":
        await agent.sleep(args.get("ms", 0))
        return None
    raise ValueError(f'Unknown skill command: "{command}"')


async def run_skill_cli(options: Dict[str, Any]) -> None:
    """Launch the JSON-lines Skill CLI for a custom interface Device class.

    Each stdin line is `{"command": "act", "args": {"prompt": "..."}}`.
    Supported commands: act, assert, query, tap, input, sleep, exit.
    """
    tools = SkillMidsceneTools(options["DeviceClass"])
    script_name = options.get("scriptName") or "midscene-skill"
    print(
        f"{script_name}: send newline-delimited JSON commands "
        '({"command": ..., "args": {...}}), one per line.',
        file=sys.stderr,
    )

    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            command = payload.get("command")
            if command in ("exit", "quit"):
                return
            agent = await tools.ensure_agent()
            result = await _run_command(agent, command, payload.get("args") or {})
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - CLI reports and exits like upstream
        raise SystemExit(report_cli_error(error)) from error


async def run_and_report(options: Dict[str, Any]) -> None:
    """Run the Skill CLI and convert failures into ``SystemExit``."""
    try:
        await run_skill_cli(options)
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001
        raise SystemExit(report_cli_error(error)) from error


__all__ = [
    "SkillMidsceneTools",
    "report_cli_error",
    "run_and_report",
    "run_skill_cli",
]
