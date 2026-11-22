"""CLI-side bridge agent (upstream bridge-mode/agent-cli-side.ts).

The CLI owns the Socket.IO bridge server; the Chrome extension drives the real
tab.  ``BridgeWebPage`` is the Python page proxy, so this module only adds the
``Agent`` lifecycle sugar the upstream CLI-side class provides.
"""

import asyncio
import inspect
from typing import Any, Dict, Optional

from loguru import logger

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.web_integration.bridge_mode.common import (
    DefaultBridgeServerPort,
    get_bridge_server_host,
)
from midscene.web_integration.bridge_mode.page_browser_side import BridgeWebPage


def get_bridge_page_in_cli_side(
    host: Optional[str] = None,
    port: Optional[int] = None,
    listening_timeout: Optional[float] = 30.0,
    close_conflict_server: bool = True,
    allow_remote_access: bool = False,
    input_strategy: Optional[str] = None,
    keyboard_type_delay: Optional[float] = None,
    connect_options: Optional[Dict[str, Any]] = None,
) -> BridgeWebPage:
    """Build the bridge page proxy without opening a socket yet."""
    return BridgeWebPage(
        host=get_bridge_server_host(host, allow_remote_access),
        port=DefaultBridgeServerPort if port is None else port,
        connect_options=connect_options,
        listening_timeout=listening_timeout,
        close_conflict_server=close_conflict_server,
        input_strategy=input_strategy,
        keyboard_type_delay=keyboard_type_delay,
    )


class AgentOverChromeBridge(Agent):
    """Core agent driving the Chrome extension bridge page."""

    def __init__(
        self,
        options: Optional[AgentOptions] = None,
        *,
        page: Optional[BridgeWebPage] = None,
        allow_remote_access: bool = False,
        host: Optional[str] = None,
        port: Optional[int] = None,
        close_new_tabs_after_disconnect: bool = False,
        server_listening_timeout: Optional[float] = 30.0,
        close_conflict_server: bool = True,
        enable_water_flow_animation: bool = True,
        input_strategy: Optional[str] = None,
        keyboard_type_delay: Optional[float] = None,
    ):
        if page is None:
            page = get_bridge_page_in_cli_side(
                host=host,
                port=port,
                listening_timeout=server_listening_timeout,
                close_conflict_server=close_conflict_server,
                allow_remote_access=allow_remote_access,
                input_strategy=input_strategy,
                keyboard_type_delay=keyboard_type_delay,
            )

        options = options or AgentOptions()
        original_on_task_start_tip = options.on_task_start_tip

        async def on_task_start_tip(tip: str) -> None:
            await page.show_status_message(tip)
            if original_on_task_start_tip is not None:
                result = original_on_task_start_tip(tip)
                if inspect.isawaitable(result):
                    await result

        options.on_task_start_tip = on_task_start_tip

        super().__init__(page, options)
        self.destroy_after_disconnect_flag = close_new_tabs_after_disconnect
        self.enable_water_flow_animation = enable_water_flow_animation

    async def _configure_water_flow_animation(self) -> None:
        if not self.enable_water_flow_animation:
            await self.interface.set_water_flow_animation_enabled(False)

    async def set_destroy_options_after_connect(self) -> None:
        if self.destroy_after_disconnect_flag:
            await self.interface.set_destroy_options({"closeTab": True})

    async def connect_new_tab_with_url(
        self, url: str, options: Optional[Dict[str, Any]] = None
    ) -> None:
        await self.interface.connect_new_tab_with_url(
            url,
            {
                **(options or {}),
                "enableWaterFlowAnimation": self.enable_water_flow_animation,
            },
        )
        await self._configure_water_flow_animation()
        await asyncio.sleep(0.5)
        await self.set_destroy_options_after_connect()

    async def connect_current_tab(
        self, options: Optional[Dict[str, Any]] = None
    ) -> None:
        await self.interface.connect_current_tab(
            {
                **(options or {}),
                "enableWaterFlowAnimation": self.enable_water_flow_animation,
            }
        )
        await self._configure_water_flow_animation()
        await asyncio.sleep(0.5)
        await self.set_destroy_options_after_connect()

    async def get_browser_tab_list(self) -> Any:
        return await self.interface.get_browser_tab_list()

    async def set_active_tab_id(self, tab_id: str) -> None:
        await self.interface.set_active_tab_id(int(tab_id))

    async def show_status_message(self, message: str) -> None:
        await self.interface.show_status_message(message)

    async def destroy(
        self, close_new_tabs_after_disconnect: Optional[bool] = None
    ) -> None:
        if close_new_tabs_after_disconnect is not None:
            await self.interface.set_destroy_options(
                {"closeTab": bool(close_new_tabs_after_disconnect)}
            )
        await super().destroy()
        close = getattr(self.interface, "close", None)
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                logger.warning(f"Failed to close bridge page: {error}")


__all__ = ["AgentOverChromeBridge", "get_bridge_page_in_cli_side"]
