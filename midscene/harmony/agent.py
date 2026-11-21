"""HarmonyOS agent (upstream HarmonyAgent extends the core Agent)."""

from typing import Dict, Optional

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.harmony.app_name_mapping import default_app_name_mapping
from midscene.harmony.device import HarmonyDevice
from midscene.shared.utils import merge_and_normalize_app_name_mapping


class HarmonyAgent(Agent):
    """AI agent controlling a HarmonyOS device through hdc."""

    def __init__(
        self,
        device: Optional[HarmonyDevice] = None,
        options: Optional[AgentOptions] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ):
        device = device or HarmonyDevice()
        super().__init__(device, options)
        device.set_app_name_mapping(
            merge_and_normalize_app_name_mapping(
                default_app_name_mapping, app_name_mapping
            )
        )
