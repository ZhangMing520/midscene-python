"""iOS device integration (upstream @midscene/ios)."""

from midscene.ios.agent import IOSAgent
from midscene.ios.device import IOSDevice
from midscene.ios.ios_webdriver_client import IOSWebDriverClient
from midscene.ios.mjpeg_frame_source import MjpegFrameSource
from midscene.ios.wda import WebDriverAgentBackend
from midscene.webdriver import WebDriverClient

__all__ = [
    "IOSAgent",
    "IOSDevice",
    "IOSWebDriverClient",
    "MjpegFrameSource",
    "WebDriverAgentBackend",
    "WebDriverClient",
]
