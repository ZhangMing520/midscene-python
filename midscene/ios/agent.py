"""iOS agent (upstream IOSAgent extends the core Agent)."""

from typing import Optional

from ..core.agent import Agent
from ..core.types import AgentOptions
from .device import IOSDevice


class IOSAgent(Agent):
    """AI agent controlling an iOS device through WebDriverAgent."""

    def __init__(
        self,
        device: Optional[IOSDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or IOSDevice(), options)
