"""iOS agent (upstream IOSAgent extends the core Agent)."""

from typing import Dict, Optional

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.ios.app_name_mapping import default_app_name_mapping
from midscene.ios.device import IOSDevice
from midscene.shared.utils import merge_and_normalize_app_name_mapping


class IOSAgent(Agent):
    """AI agent controlling an iOS device through WebDriverAgent."""

    def __init__(
        self,
        device: Optional[IOSDevice] = None,
        options: Optional[AgentOptions] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ):
        super().__init__(device or IOSDevice(), options)
        device = self.interface
        if isinstance(device, IOSDevice):
            device.set_app_name_mapping(
                merge_and_normalize_app_name_mapping(
                    default_app_name_mapping, app_name_mapping
                )
            )
