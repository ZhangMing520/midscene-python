"""iOS helpers (upstream utils.ts)."""

import asyncio
import platform


def check_mac_os_platform() -> dict[str, object]:
    """Report whether the host is macOS (upstream checkMacOSPlatform)."""
    current_platform = platform.system().lower()
    # Node's os.platform() reports "win32"; normalize Python's "windows" so
    # downstream messages keep the upstream value.
    if current_platform == "windows":
        current_platform = "win32"
    return {
        "isMacOS": current_platform == "darwin",
        "platform": current_platform,
    }


def check_macos_platform() -> dict[str, object]:
    """Backward-compatible alias of :func:`check_mac_os_platform`."""
    return check_mac_os_platform()


async def check_ios_environment() -> dict[str, object]:
    """Check xcode command-line tooling availability (upstream)."""
    platform_check = check_mac_os_platform()
    if not platform_check["isMacOS"]:
        return {
            "available": False,
            "error": (
                "iOS development is only supported on macOS. Current platform: "
                f"{platform_check['platform']}"
            ),
        }

    xcrun_path = await _run_command("which xcrun")
    if not xcrun_path.strip():
        return {
            "available": False,
            "error": (
                "xcrun not found. Please install Xcode Command Line Tools: "
                "xcode-select --install"
            ),
        }

    if not await _command_succeeds("xcodebuild -version"):
        return {
            "available": False,
            "error": "xcodebuild not found. Please install Xcode from the App Store",
        }

    return {"available": True}


async def _run_command(command: str) -> str:
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    return stdout.decode("utf-8", errors="ignore")


async def _command_succeeds(command: str) -> bool:
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
    return process.returncode == 0


def screenshots_similar(before: str, after: str, tolerance_percent: float) -> bool:
    """Compare base64 screenshots while tolerating a little dynamic content.

    Upstream compares the encoded text directly: animated clocks and badges
    change a small fraction of the characters, so a threshold on the sampled
    prefix is enough to tell "the page stopped moving" from "still scrolling".
    """
    if before == after:
        return True
    shortest = min(len(before), len(after))
    if not shortest:
        return False
    if abs(len(before) - len(after)) > shortest * 0.1:
        return False
    sample = min(2000, shortest)
    diff_count = sum(1 for i in range(sample) if before[i] != after[i])
    return (diff_count / sample) * 100 <= tolerance_percent


__all__ = [
    "check_ios_environment",
    "check_mac_os_platform",
    "check_macos_platform",
    "screenshots_similar",
]
