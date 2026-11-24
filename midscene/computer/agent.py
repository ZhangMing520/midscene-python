"""Computer agent (upstream packages/computer/src/agent.ts)."""

import re
from dataclasses import fields
from typing import Any

from midscene.computer.device import ComputerDevice
from midscene.computer.rdp.device import RDPDevice
from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions


def _camel_to_snake(value: str) -> str:
    step = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return step.lower()


def _option(opts: Any, name: str, default: Any = None) -> Any:
    """Read a snake_case or camelCase option from a mapping or object."""
    if opts is None:
        return default
    candidates = (name, _camel_to_snake(name))
    for candidate in candidates:
        if isinstance(opts, dict) and candidate in opts:
            return opts[candidate]
        if hasattr(opts, candidate):
            return getattr(opts, candidate)
    camel = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), name)
    if isinstance(opts, dict):
        return opts.get(camel, default)
    return getattr(opts, camel, default)


def _agent_options(opts: Any) -> AgentOptions | None:
    """Build AgentOptions from a mapping while ignoring device-only keys."""
    if opts is None:
        return None
    if isinstance(opts, AgentOptions):
        return opts
    if not isinstance(opts, dict):
        return opts
    options = AgentOptions()
    known = {field.name for field in fields(AgentOptions)}
    for key, value in opts.items():
        snake = _camel_to_snake(key)
        if snake in known:
            setattr(options, snake, value)
    return options


class ComputerAgent(Agent):
    """AI agent controlling the local computer (Windows / macOS / Linux)."""

    def __init__(
        self,
        device: ComputerDevice | None = None,
        options: AgentOptions | None = None,
    ):
        super().__init__(device or ComputerDevice(), options)


async def agent_for_computer(opts: Any = None) -> ComputerAgent:
    """Create and connect an agent for the local desktop."""
    device = ComputerDevice(
        display_id=_option(opts, "display_id"),
        keyboard_modifier_delay=_option(opts, "keyboard_modifier_delay") or 0,
        headless=bool(_option(opts, "headless")),
    )
    await device.connect()
    return ComputerAgent(device, _agent_options(opts))


async def agent_for_rdp_computer(opts: Any) -> ComputerAgent:
    """Create and connect an agent for a remote RDP desktop."""
    config_keys = (
        "host",
        "port",
        "username",
        "password",
        "domain",
        "local_address",
        "admin_session",
        "ignore_certificate",
        "security_protocol",
        "desktop_width",
        "desktop_height",
    )
    config: dict[str, Any] = {}
    for key in config_keys:
        value = _option(opts, key)
        if value is None:
            continue
        camel = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)
        config[camel] = value
    device = RDPDevice(config, _option(opts, "backend"))
    await device.connect()
    return ComputerAgent(device, _agent_options(opts))


# Backward-compatible alias (upstream deprecated agentFromComputer).
agent_from_computer = agent_for_computer


__all__ = [
    "ComputerAgent",
    "agent_for_computer",
    "agent_from_computer",
    "agent_for_rdp_computer",
]
