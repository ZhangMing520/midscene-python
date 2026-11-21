"""Computer agent (upstream packages/computer/src/agent.ts)."""

from typing import Optional

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.computer.device import ComputerDevice


class ComputerAgent(Agent):
    """AI agent controlling the local computer (Windows / macOS / Linux)."""

    def __init__(
        self,
        device: Optional[ComputerDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or ComputerDevice(), options)

