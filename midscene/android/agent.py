"""
Android Agent implementation
"""

from typing import Dict, Optional

from midscene.core.agent.agent import Agent, AgentOptions
from midscene.android.app_name_mapping import default_app_name_mapping
from midscene.android.device import AndroidDevice
from midscene.shared.utils import merge_and_normalize_app_name_mapping


class AndroidAgent(Agent):
    """Android-specific agent implementation"""
    
    def __init__(
        self,
        device: AndroidDevice,
        options: Optional[AgentOptions] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ):
        """Initialize Android agent
        
        Args:
            device: AndroidDevice instance
            options: Agent options
            app_name_mapping: Custom friendly-name -> package-name mapping;
                user entries take precedence over the built-in mapping.
        """
        super().__init__(device, options)
        device.set_app_name_mapping(
            merge_and_normalize_app_name_mapping(
                default_app_name_mapping, app_name_mapping
            )
        )
        
        # Validate that we have vision language model support for Android
        # Android requires VL models for UI understanding
        
    @classmethod
    async def create(
        cls, 
        device_id: Optional[str] = None,
        options: Optional[AgentOptions] = None,
        app_name_mapping: Optional[Dict[str, str]] = None,
    ) -> 'AndroidAgent':
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
    
    async def launch_app(self, package_name: str, activity: Optional[str] = None) -> None:
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
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        duration: int = 300
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