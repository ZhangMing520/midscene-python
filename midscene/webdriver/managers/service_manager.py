"""Base WebDriver service manager (upstream managers/ServiceManager.ts)."""

from abc import ABC, abstractmethod


class BaseServiceManager(ABC):
    """Shared lifecycle/address helpers for WebDriver services."""

    def __init__(self, port: int, host: str = "localhost"):
        self.port = port
        self.host = host

    @abstractmethod
    async def start(self) -> None:
        """Start the service."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the service."""

    @abstractmethod
    def is_running(self) -> bool:
        """Whether the service is considered started."""

    async def restart(self) -> None:
        if self.is_running():
            await self.stop()
        await self.start()

    def get_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    def get_port(self) -> int:
        return self.port

    def get_host(self) -> str:
        return self.host


__all__ = ["BaseServiceManager"]
