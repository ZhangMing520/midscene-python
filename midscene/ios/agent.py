"""iOS agent (upstream IOSAgent extends the core Agent)."""

from typing import Optional

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.ios.device import IOSDevice


class IOSAgent(Agent):
    """AI agent controlling an iOS device through WebDriverAgent."""

    def __init__(
        self,
        device: Optional[IOSDevice] = None,
        options: Optional[AgentOptions] = None,
    ):
        super().__init__(device or IOSDevice(), options)
