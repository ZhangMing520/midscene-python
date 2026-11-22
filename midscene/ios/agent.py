"""iOS agent (upstream IOSAgent extends the core Agent)."""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import coerce_agent_options
from midscene.ios.app_name_mapping import default_app_name_mapping
from midscene.ios.device import IOSDevice
from midscene.ios.wda_options import assert_wda_connection_options
from midscene.shared.env.constants import MIDSCENE_IOS_DEVICE_CLASS_OVERRIDE
from midscene.shared.utils import merge_and_normalize_app_name_mapping


def _option(options: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(options, dict) and key in options:
            return options[key]
        if not isinstance(options, dict) and hasattr(options, key):
            return getattr(options, key)
    return None


class IOSAgent(Agent):
    """AI agent controlling an iOS device through WebDriverAgent."""

    @staticmethod
    def get_test_runner_node_definitions() -> List[Any]:
        """Common Agent nodes (platform bindings live in the Node-only module)."""
        return Agent.get_test_runner_node_definitions()

    def __init__(
        self,
        device: Optional[IOSDevice] = None,
        options: Optional[Any] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ):
        app_name_mapping = app_name_mapping or _option(
            options, "appNameMapping", "app_name_mapping"
        )
        super().__init__(device or IOSDevice(), coerce_agent_options(options))
        target = device or self.interface
        if hasattr(target, "set_app_name_mapping"):
            target.set_app_name_mapping(
                merge_and_normalize_app_name_mapping(
                    default_app_name_mapping, app_name_mapping
                )
            )

    async def launch(self, uri: str) -> None:
        """Launch an iOS app or URL (upstream launch)."""
        await self._call_action_in_action_space("Launch", {"uri": uri})

    async def terminate(self, uri: str) -> None:
        """Close an iOS app by bundle ID (upstream terminate)."""
        await self._call_action_in_action_space("Terminate", {"uri": uri})


def _load_overridden_device_class(module_target: str) -> Any:
    try:
        path = Path(module_target)
        if path.suffix == ".py" and path.exists():
            spec = importlib.util.spec_from_file_location(
                "midscene_ios_device_override", str(path)
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load module from {module_target}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(module_target)
    except Exception as error:  # noqa: BLE001 - mirror upstream wrapping
        raise RuntimeError(
            "Failed to load iOS device class override from "
            f'"{module_target}". Please make sure the package is installed and '
            "exports IOSDevice (or default) with Midscene-compatible methods. "
            f"Original error: {error}"
        ) from error

    device_class = getattr(module, "IOSDevice", None)
    if device_class is None:
        device_class = getattr(module, "default", None)
    if not callable(device_class):
        raise RuntimeError(
            "Failed to load iOS device class override from "
            f'"{module_target}". Please make sure the package is installed and '
            "exports IOSDevice (or default) with Midscene-compatible methods. "
            f'Original error: Module "{module_target}" does not export a valid '
            'iOS device class (expected "IOSDevice" or default export).'
        )
    return device_class


async def agent_from_web_driver_agent(
    options: Optional[Any] = None,
) -> IOSAgent:
    """Create an iOS agent backed by a running WebDriverAgent (upstream)."""
    if isinstance(options, dict):
        assert_wda_connection_options(options)
    logger.debug("Creating iOS agent with WebDriverAgent")

    override_module = None
    if isinstance(options, dict):
        override_module = options.get("iOSDeviceClassOverride")
    override_module = (
        str(override_module).strip() if override_module else None
    ) or (os.environ.get(MIDSCENE_IOS_DEVICE_CLASS_OVERRIDE) or "").strip()

    device_class = IOSDevice
    if override_module:
        device_class = _load_overridden_device_class(override_module)

    device_options = options if isinstance(options, dict) else {}
    device = device_class(device_options)
    await device.connect()
    return IOSAgent(device, options)


__all__ = ["IOSAgent", "agent_from_web_driver_agent"]
