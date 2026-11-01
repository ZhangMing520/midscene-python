"""HarmonyOS agent (upstream HarmonyAgent extends the core Agent)."""

from typing import Optional

from ..core.agent import Agent
from ..core.types import AgentOptions
from .device import HarmonyDevice


class HarmonyAgent(Agent):
    """AI agent controlling a HarmonyOS device through hdc."""

    def __init__(
        self,
        device: Optional[HarmonyDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or HarmonyDevice(), options)
