"""HarmonyOS agent (upstream HarmonyAgent extends the core Agent)."""

from typing import Any, cast

from loguru import logger

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import coerce_agent_options
from midscene.harmony.app_name_mapping import default_app_name_mapping
from midscene.harmony.device import HarmonyDevice
from midscene.harmony.utils import get_connected_devices
from midscene.shared.utils import merge_and_normalize_app_name_mapping


def _option(options: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(options, dict) and key in options:
            return options[key]
        if not isinstance(options, dict) and hasattr(options, key):
            return getattr(options, key)
    return None


class HarmonyAgent(Agent):
    """AI agent controlling a HarmonyOS device through hdc."""

    @staticmethod
    def get_test_runner_node_definitions() -> list[Any]:
        """Common Agent nodes (platform bindings live in the Node-only module)."""
        return Agent.get_test_runner_node_definitions()

    def __init__(
        self,
        device: HarmonyDevice | None = None,
        options: Any | None = None,
        app_name_mapping: dict[str, str] | None = None,
    ):
        app_name_mapping = app_name_mapping or _option(
            options, "appNameMapping", "app_name_mapping"
        )
        device = device or HarmonyDevice()
        super().__init__(device, coerce_agent_options(options))
        device.set_app_name_mapping(
            merge_and_normalize_app_name_mapping(
                default_app_name_mapping, app_name_mapping
            )
        )

    async def launch(self, uri: str) -> None:
        """Launch a HarmonyOS app or URL (upstream launch)."""
        await self._call_action_in_action_space("Launch", {"uri": uri})

    async def terminate(self, uri: str) -> None:
        """Terminate a HarmonyOS app by bundle name (upstream terminate)."""
        await self._call_action_in_action_space("Terminate", {"uri": uri})

    async def run_hdc_shell(self, command: str) -> str:
        """Execute an HDC shell command through the RunHdcShell action."""
        # RunHdcShell's action executor returns the command's stdout string.
        return cast(
            str,
            await self._call_action_in_action_space(
                "RunHdcShell", {"command": command}
            ),
        )


async def agent_from_hdc_device(
    device_id: str | None = None,
    options: Any | None = None,
) -> HarmonyAgent:
    """Create a HarmonyOS agent from a connected HDC device (upstream)."""
    device_options = options if isinstance(options, dict) else {}
    if not device_id:
        devices = await get_connected_devices(
            _option(device_options, "hdcPath", "hdc_path")
        )

        if not devices:
            raise RuntimeError(
                "No HarmonyOS devices found. Please connect a HarmonyOS device "
                "and ensure HDC is properly configured. Run "
                "`hdc list targets` to verify device connection."
            )

        first_device = devices[0]
        device_id = (
            first_device.get("deviceId")
            if isinstance(first_device, dict)
            else getattr(first_device, "device_id", None)
        )
        logger.debug(
            f"deviceId not specified, will use the first device (id = {device_id})"
        )

    # Device discovery is an external boundary; the selected entry supplies the id.
    device = HarmonyDevice(cast(str, device_id), device_options)
    await device.connect()
    return HarmonyAgent(device, options)


__all__ = ["HarmonyAgent", "agent_from_hdc_device"]
