"""Browser agent helpers (upstream common/browser-agent-utils.ts).

Upstream ports the retryable-navigation-error predicate and the Chrome
``select`` rendering patch.  The screenshot/viewport helpers are the Python
side counterpart of the context capture that the Playwright page used to own
inline.
"""

import base64
import importlib.metadata
import re
from typing import Any, Dict, Optional

from loguru import logger

from midscene.core.agent.common import BROWSER_NAVIGATION_ERROR_PATTERN
from midscene.core.types import Size

BROWSER_RUNTIME_CONFIG: Dict[str, Dict[str, str]] = {
    "puppeteer": {
        "display_name": "Puppeteer",
        "package_name": "puppeteer",
        "minimum_version": "24.6.0",
        "requirement_label": "> 24.6.0",
    },
    "playwright": {
        "display_name": "Playwright",
        "package_name": "playwright",
        "minimum_version": "1.52.0",
        "requirement_label": ">= 1.52.0",
    },
}

_CHROME_SELECT_STYLE_ID = "midscene-force-select-rendering"
_CHROME_SELECT_INIT_SCRIPT = """
(() => {
  const addStyle = () => {
    if (document.getElementById('%s')) return;
    const style = document.createElement('style');
    style.id = '%s';
    style.textContent =
      'select, select::picker(select) { appearance: base-select !important; }';
    document.head && document.head.appendChild(style);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addStyle, { once: true });
  } else {
    addStyle();
  }
})();
""" % (_CHROME_SELECT_STYLE_ID, _CHROME_SELECT_STYLE_ID)


def is_retryable_browser_navigation_error(error: BaseException) -> bool:
    """Whether a browser context error is a transient navigation race."""
    return isinstance(error, BaseException) and bool(
        BROWSER_NAVIGATION_ERROR_PATTERN.search(str(error) or "")
    )


def _version_tuple(version: str) -> "tuple[int, ...]":
    parts = re.findall(r"\d+", version or "")
    return tuple(int(part) for part in parts[:3])


def _version_at_least(version: str, minimum: str) -> bool:
    current = _version_tuple(version)
    required = _version_tuple(minimum)
    length = max(len(current), len(required))
    return current + (0,) * (length - len(current)) >= required + (
        0,
    ) * (length - len(required))


def _get_package_version(package_name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception as error:  # package metadata can be missing or corrupted
        logger.error(f"Failed to get {package_name} version: {error}")
        return None


async def apply_force_chrome_select_rendering(
    page: Any, runtime: str = "playwright", enabled: bool = True
) -> None:
    """Patch select rendering on a Playwright page (upstream
    applyForceChromeSelectRendering)."""
    if enabled is False:
        return

    config = BROWSER_RUNTIME_CONFIG.get(runtime)
    if enabled is True and config is not None:
        version = _get_package_version(config["package_name"])
        if version and not _version_at_least(
            version, config["minimum_version"]
        ):
            logger.warning(
                "[midscene:error] forceChromeSelectRendering requires "
                f"{config['display_name']} {config['requirement_label']}, but "
                f"current version is {version}. This feature may not work "
                "correctly."
            )

    await page.add_init_script(_CHROME_SELECT_INIT_SCRIPT)
    await page.evaluate(_CHROME_SELECT_INIT_SCRIPT)


async def take_screenshot_base64(page: Any) -> str:
    """Take a PNG screenshot and return its base64 payload."""
    screenshot_bytes = await page.screenshot(type="png")
    return base64.b64encode(screenshot_bytes).decode("utf-8")


async def get_page_size(page: Any) -> Size:
    """Read the logical viewport size, defaulting to 1920x1080 on failure."""
    viewport_size = await page.evaluate(
        """
        () => ({
            width: window.innerWidth,
            height: window.innerHeight
        })
    """
    )
    return Size(width=viewport_size["width"], height=viewport_size["height"])


__all__ = [
    "BROWSER_RUNTIME_CONFIG",
    "_CHROME_SELECT_INIT_SCRIPT",
    "apply_force_chrome_select_rendering",
    "get_page_size",
    "is_retryable_browser_navigation_error",
    "take_screenshot_base64",
]
