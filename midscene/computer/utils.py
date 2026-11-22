"""Computer helpers (upstream utils.ts)."""

import platform
from typing import Any, Dict, List


def version() -> str:
    import midscene

    return midscene.__version__


def is_mac() -> bool:
    """True on macOS; the modifier key differs there (Cmd vs Ctrl/Win)."""
    return platform.system() == "Darwin"


def _platform_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    if system == "Windows":
        return "win32"
    return system.lower() or "linux"


def _load_application_services():
    import ctypes

    return ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/"
        "ApplicationServices"
    )


def _load_core_graphics():
    import ctypes

    return ctypes.CDLL(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )


def _open_privacy_pane(anchor: str) -> None:
    import subprocess

    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.preference.security?"
            f"Privacy_{anchor}",
        ],
        check=False,
    )


def check_accessibility_permission(
    prompt_if_needed: bool = False,
) -> Dict[str, Any]:
    """Check the macOS Accessibility permission (always granted elsewhere)."""
    system = _platform_name()
    if system != "darwin":
        return {"hasPermission": True, "platform": system}

    try:
        services = _load_application_services()
        trusted = bool(services.AXIsProcessTrusted())
        if trusted:
            return {"hasPermission": True, "platform": system}
        if prompt_if_needed:
            _open_privacy_pane("Accessibility")
        return {
            "hasPermission": False,
            "platform": system,
            "error": (
                "macOS Accessibility permission is required.\n\n"
                "Please follow these steps:\n"
                "1. Open System Settings > Privacy & Security > Accessibility\n"
                "2. Enable the application running this script "
                "(e.g., Terminal, iTerm2, VS Code, WebStorm)\n"
                "3. Restart your terminal or IDE after granting permission\n\n"
                "For more details, see: https://github.com/nut-tree/nut.js#macos"
            ),
        }
    except Exception as error:
        return {
            "hasPermission": False,
            "platform": system,
            "error": f"Failed to check accessibility permission: {error}",
        }


def check_screen_recording_permission(
    prompt_if_needed: bool = False,
) -> Dict[str, Any]:
    """Check the macOS Screen Recording permission (granted elsewhere)."""
    system = _platform_name()
    if system != "darwin":
        return {"hasPermission": True, "platform": system}

    try:
        quartz = _load_core_graphics()
        allowed = bool(quartz.CGPreflightScreenCaptureAccess())
        if allowed:
            return {"hasPermission": True, "platform": system}
        if prompt_if_needed:
            quartz.CGRequestScreenCaptureAccess()
        return {
            "hasPermission": False,
            "platform": system,
            "error": (
                "macOS Screen Recording permission is required.\n\n"
                "Please follow these steps:\n"
                "1. Open System Settings > Privacy & Security > Screen Recording\n"
                "2. Enable the application running this script "
                "(e.g., Terminal, iTerm2, VS Code, WebStorm, or Midscene Studio)\n"
                "3. Fully quit and relaunch that application after granting "
                "permission — macOS only re-reads this permission on process "
                "launch."
            ),
        }
    except Exception as error:
        return {
            "hasPermission": False,
            "platform": system,
            "error": f"Failed to check screen recording permission: {error}",
        }


async def check_computer_environment() -> Dict[str, Any]:
    """Check whether the desktop automation backend can capture the screen."""
    from midscene.computer.device import ComputerDevice
    from midscene.computer.input_driver import load_pyautogui

    system = _platform_name()
    try:
        pyautogui = await load_pyautogui()
        screen_size = pyautogui.size()
        if not screen_size or screen_size.width <= 0:
            return {
                "available": False,
                "error": "screen backend cannot get screen size",
                "platform": system,
                "displays": 0,
            }
        displays = await ComputerDevice.list_displays()
        return {
            "available": True,
            "platform": system,
            "displays": len(displays),
        }
    except Exception as error:
        return {
            "available": False,
            "error": str(error),
            "platform": system,
            "displays": 0,
        }


async def get_connected_displays() -> List[Dict[str, Any]]:
    """Get all connected displays."""
    from midscene.computer.device import ComputerDevice

    return await ComputerDevice.list_displays()


__all__ = [
    "check_accessibility_permission",
    "check_computer_environment",
    "check_screen_recording_permission",
    "get_connected_displays",
    "is_mac",
    "version",
]
