"""HarmonyOS agent (upstream HarmonyAgent extends the core Agent)."""

from typing import Optional

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.harmony.device import HarmonyDevice


class HarmonyAgent(Agent):
    """AI agent controlling a HarmonyOS device through hdc."""

    def __init__(
        self,
        device: Optional[HarmonyDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or HarmonyDevice(), options)
