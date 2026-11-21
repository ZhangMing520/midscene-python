"""WebDriverAgent lifecycle manager (upstream managers/WDAManager.ts).

WebDriverAgent must already be running: this manager verifies reachability
and reports the configured endpoint, but never launches Xcode for the caller.
"""

import asyncio
import time
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from midscene.shared.constants import DEFAULT_WDA_PORT
from midscene.webdriver.managers.service_manager import BaseServiceManager
from midscene.webdriver.utils.base_url import normalize_webdriver_base_url


class WDAManager(BaseServiceManager):
    """Process-wide WDA manager keyed by endpoint."""

    _instances: Dict[str, "WDAManager"] = {}

    def __init__(
        self,
        port: int = DEFAULT_WDA_PORT,
        host: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        address = urlparse(base_url) if base_url else None
        if address is not None:
            parsed_port = address.port or (
                443 if address.scheme == "https" else 80
            )
            parsed_host = address.hostname or host or "localhost"
        else:
            parsed_port = port
            parsed_host = host or "localhost"

        super().__init__(parsed_port, parsed_host)
        self._base_url = base_url or super().get_endpoint()
        self._is_started = False

    @classmethod
    def get_instance(
        cls,
        port: int = DEFAULT_WDA_PORT,
        host: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> "WDAManager":
        key = (
            normalize_webdriver_base_url(base_url)
            if base_url is not None
            else f"http://{host or 'localhost'}:{port}"
        )
        if key not in cls._instances:
            cls._instances[key] = cls(port=port, host=host, base_url=key)
        return cls._instances[key]

    async def start(self) -> None:
        if self._is_started:
            logger.debug("WDA already started")
            return

        try:
            # Device connection and port forwarding are handled externally;
            # only reachability of WebDriverAgent is checked here.
            if await self._is_wda_running():
                logger.debug("WDA already running")
                self._is_started = True
                return

            await self._start_wda()
            await self._wait_for_wda()
            self._is_started = True
            logger.debug("WDA started successfully")
        except Exception as error:  # noqa: BLE001 - mirror upstream wrapping
            logger.debug(f"Failed to start WDA: {error}")
            raise RuntimeError(
                f"Failed to start WebDriverAgent: {error}"
            ) from error

    async def stop(self) -> None:
        if not self._is_started:
            return
        # Cleanup is best-effort: the WDA process is owned by the caller.
        self._is_started = False
        logger.debug("WDA stopped")

    def is_running(self) -> bool:
        return self._is_started

    def get_endpoint(self) -> str:
        return self._base_url

    async def _start_wda(self) -> None:
        await self._check_wda_preparation()
        logger.debug("WebDriverAgent verification completed")

    async def _check_wda_preparation(self) -> None:
        if await self._is_wda_running():
            logger.debug("WebDriverAgent is already running")
            return

        raise RuntimeError(
            "WebDriverAgent is not reachable at the configured address. "
            "Please start WebDriverAgent manually or check the gateway route:\n\n"
            "Setup Instructions:\n"
            "1. Install WebDriverAgent: npm install appium-webdriveragent\n"
            "2. Build and run WebDriverAgent:\n"
            "   - For simulators: Use Xcode to run WebDriverAgentRunner "
            "on your target simulator\n"
            "   - For real devices: Build WebDriverAgentRunner and install "
            "on your device\n"
            "3. Ensure WebDriverAgent is reachable at the configured address\n\n"
            "Alternative: You can also specify a different host/port where "
            "WebDriverAgent is running."
        )

    async def _is_wda_running(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.get_endpoint()}/status")
            if response.status_code >= 400:
                return False
            return "sessionId" in response.text
        except Exception:  # noqa: BLE001 - unreachable means not running
            return False

    async def _wait_for_wda(self, timeout: float = 30_000) -> None:
        """Wait until WDA answers, treating `timeout` as milliseconds."""
        start_time = time.monotonic()
        while (time.monotonic() - start_time) * 1000 < timeout:
            if await self._is_wda_running():
                return
            await asyncio.sleep(1)
        raise RuntimeError(
            f"WebDriverAgent did not start within {timeout}ms"
        )


__all__ = ["WDAManager"]
