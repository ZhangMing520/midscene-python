"""Skill CLI over a custom Device class (upstream core/src/skill/index.ts).

The upstream module delegates to ``@midscene/shared/cli``'s tools runner. The
Python port uses the same framework: ``BaseMidsceneTools`` generates the tool
definitions from the device action space, and ``run_tools_cli`` exposes them as
``<script> <command> [options]`` CLI commands.
"""

from typing import Any, Optional

from midscene.core.agent.agent import Agent
from midscene.shared.agent_tools.base_tools import BaseMidsceneTools
from midscene.shared.cli import report_cli_error, run_tools_cli


class SkillMidsceneTools(BaseMidsceneTools):
    """Lazily creates an Agent from a Device class for CLI / Agent Skills."""

    def __init__(self, device_class: type[Any]) -> None:
        super().__init__()
        self._device_class = device_class

    def create_temporary_device(self) -> Any:
        return self._device_class()

    async def ensure_agent(self, init_param: Any = None) -> Any:
        if self.agent is None:
            self.agent = Agent(self._device_class())
        return self.agent


async def run_skill_cli(options: dict[str, Any]) -> None:
    """Launch a Skill CLI for a custom interface Device class.

    This enables AI coding assistants (Claude Code, Cline, etc.) to control a
    custom interface through CLI commands.

    Example:
        ``run_skill_cli({"DeviceClass": SampleDevice, "scriptName": "my-device"})``
    """
    tools = SkillMidsceneTools(options["DeviceClass"])
    script_name = options.get("scriptName") or "midscene-skill"
    try:
        await run_tools_cli(tools, script_name)
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - CLI reports and exits
        raise SystemExit(report_cli_error(error)) from error


__all__ = ["SkillMidsceneTools", "run_skill_cli"]
