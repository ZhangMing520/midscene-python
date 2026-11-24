"""Android Agent implementation (upstream android/src/agent.ts)."""

from typing import Any, cast

from loguru import logger

from midscene.android.app_name_mapping import default_app_name_mapping
from midscene.android.device import AndroidDevice
from midscene.android.utils import get_connected_devices
from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions, coerce_agent_options
from midscene.shared.utils import merge_and_normalize_app_name_mapping


def _option(options: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(options, dict) and key in options:
            return options[key]
        if not isinstance(options, dict) and hasattr(options, key):
            return getattr(options, key)
    return None


class AndroidAgent(Agent):
    """Android-specific agent implementation"""

    @staticmethod
    def get_test_runner_node_definitions() -> list[Any]:
        """Common Agent nodes (platform bindings live in the Node-only module)."""
        return Agent.get_test_runner_node_definitions()

    def __init__(
        self,
        device: AndroidDevice,
        options: Any | None = None,
        app_name_mapping: dict[str, str] | None = None,
    ):
        """Initialize Android agent

        Args:
            device: AndroidDevice instance
            options: AgentOptions or an upstream-style options dict
            app_name_mapping: Custom friendly-name -> package-name mapping;
                user entries take precedence over the built-in mapping.
        """
        app_name_mapping = app_name_mapping or _option(
            options, "appNameMapping", "app_name_mapping"
        )
        super().__init__(device, coerce_agent_options(options))
        self.interface: AndroidDevice = device
        device.set_app_name_mapping(
            merge_and_normalize_app_name_mapping(
                default_app_name_mapping, app_name_mapping
            )
        )

    @classmethod
    async def create(
        cls,
        device_id: str | None = None,
        options: AgentOptions | None = None,
        app_name_mapping: dict[str, str] | None = None,
    ) -> "AndroidAgent":
        """Create Android agent with device

        Args:
            device_id: Android device ID, if None uses first available
            options: Agent options
            app_name_mapping: Custom friendly-name -> package-name mapping

        Returns:
            AndroidAgent instance
        """
        device = await AndroidDevice.create(device_id)
        return cls(device, options, app_name_mapping)

    async def launch(self, uri: str) -> None:
        """Launch an Android app or URL (upstream launch)."""
        await self._call_action_in_action_space("Launch", {"uri": uri})

    async def terminate(self, uri: str) -> None:
        """Force-stop an Android app by package name (upstream terminate)."""
        await self._call_action_in_action_space("Terminate", {"uri": uri})

    async def run_adb_shell(
        self, command: str, opt: dict[str, Any] | None = None
    ) -> str:
        """Execute an ADB shell command through the RunAdbShell action."""
        param: dict[str, Any] = {"command": command}
        param.update(opt or {})
        # RunAdbShell's action executor returns the command's stdout string.
        return cast(str, await self._call_action_in_action_space("RunAdbShell", param))

    async def launch_app(self, package_name: str, activity: str | None = None) -> None:
        """Launch Android app

        Args:
            package_name: App package name
            activity: Optional activity name
        """
        await self.interface.launch_app(package_name, activity)

    async def stop_app(self, package_name: str) -> None:
        """Stop Android app

        Args:
            package_name: App package name
        """
        await self.interface.stop_app(package_name)

    async def install_app(self, apk_path: str) -> None:
        """Install Android app

        Args:
            apk_path: Path to APK file
        """
        await self.interface.install_app(apk_path)

    async def back(self) -> None:
        """Press back button"""
        await self.interface.back()

    async def home(self) -> None:
        """Press home button"""
        await self.interface.home()

    async def recent(self) -> None:
        """Press recent apps button"""
        await self.interface.recent()

    async def swipe(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        duration: int = 300,
    ) -> None:
        """Swipe gesture

        Args:
            start_x: Start X coordinate
            start_y: Start Y coordinate
            end_x: End X coordinate
            end_y: End Y coordinate
            duration: Swipe duration in milliseconds
        """
        await self.interface.swipe(start_x, start_y, end_x, end_y, duration)

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        """Long press gesture

        Args:
            x: X coordinate
            y: Y coordinate
            duration: Press duration in milliseconds
        """
        await self.interface.long_press(x, y, duration)


async def agent_from_adb_device(
    device_id: str | None = None,
    options: Any | None = None,
) -> AndroidAgent:
    """Create an Android agent from a connected ADB device (upstream)."""
    device_options = options if isinstance(options, dict) else {}
    if not device_id:
        devices = await get_connected_devices(device_options)

        if not devices:
            raise RuntimeError(
                "No Android devices found. Please connect an Android device and "
                "ensure ADB is properly configured. Run `adb devices` to verify "
                "device connection."
            )

        first_device = devices[0]
        device_id = (
            first_device.get("udid")
            if isinstance(first_device, dict)
            else getattr(first_device, "udid", None)
        )
        logger.debug(
            f"deviceId not specified, will use the first device (id = {device_id})"
        )

    # Device discovery is an external boundary; the selected entry supplies the id.
    device = AndroidDevice(cast(str, device_id), device_options)
    await device.connect()
    return AndroidAgent(device, options)


__all__ = ["AndroidAgent", "agent_from_adb_device"]
