"""Desktop agent (upstream ComputerAgent extends the core Agent)."""

from typing import Optional

from ..core.agent import Agent
from ..core.types import AgentOptions
from .desktop import DesktopDevice


class DesktopAgent(Agent):
    """AI agent controlling the local desktop (Windows / macOS / Linux)."""

    def __init__(
        self,
        device: Optional[DesktopDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or DesktopDevice(), options)
