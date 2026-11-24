"""uiautomator hierarchy capture (upstream android/src/ui-tree-capture.ts).

The upstream module validates multi-display alignment; the Python SDK has no
multi-display tree model, so capture focuses on retrying the dump and
validating the XML envelope.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable

from loguru import logger

ACCESSIBILITY_DUMP_ATTEMPTS = 3
ACCESSIBILITY_DUMP_TIMEOUT_MS = 5_000
ACCESSIBILITY_DUMP_RETRY_DELAY_MS = 250
UIAUTOMATOR_LAYOUT_PATH = "/sdcard/midscene_window_dump.xml"

RunAdbCommand = Callable[..., Awaitable[object]]

_HIERARCHY_OPEN = re.compile(r"<hierarchy(?:\s|>)")


def _validate_hierarchy_xml(xml: object) -> str:
    if (
        not isinstance(xml, str)
        or not _HIERARCHY_OPEN.search(xml)
        or "</hierarchy>" not in xml
    ):
        raise RuntimeError("uiautomator did not produce valid hierarchy XML")
    return xml


async def capture_android_ui_tree(
    run_adb_command: RunAdbCommand, device_id: str
) -> str:
    """Dump the accessibility hierarchy, retrying transient failures."""
    failures: list[str] = []
    shell_prefix = ["-s", device_id, "shell"]

    for attempt in range(1, ACCESSIBILITY_DUMP_ATTEMPTS + 1):
        try:
            await run_adb_command(
                [*shell_prefix, "rm", "-f", UIAUTOMATOR_LAYOUT_PATH],
                timeout=ACCESSIBILITY_DUMP_TIMEOUT_MS,
            )
            await run_adb_command(
                [
                    *shell_prefix,
                    "uiautomator",
                    "dump",
                    "--compressed",
                    UIAUTOMATOR_LAYOUT_PATH,
                ],
                timeout=ACCESSIBILITY_DUMP_TIMEOUT_MS,
            )
            result = await run_adb_command(
                [*shell_prefix, "cat", UIAUTOMATOR_LAYOUT_PATH],
                capture_output=True,
                timeout=ACCESSIBILITY_DUMP_TIMEOUT_MS,
            )
            xml = _validate_hierarchy_xml(
                result.stdout.decode("utf-8", errors="ignore")
            )
            logger.debug(
                f"android ui tree captured: attempt={attempt} bytes={len(xml)}"
            )
            return xml
        except Exception as error:  # noqa: BLE001 - retried below
            failures.append(
                f"uiautomator attempt {attempt}/{ACCESSIBILITY_DUMP_ATTEMPTS}: {error}"
            )
            logger.debug(
                f"android ui tree capture failed: attempt={attempt} error={error}"
            )
            if attempt < ACCESSIBILITY_DUMP_ATTEMPTS:
                await asyncio.sleep(ACCESSIBILITY_DUMP_RETRY_DELAY_MS / 1000.0)

    raise RuntimeError(
        "Unable to capture Android UI tree after "
        f"{len(failures)} attempt(s): {'; '.join(failures)}"
    )


__all__ = [
    "ACCESSIBILITY_DUMP_ATTEMPTS",
    "ACCESSIBILITY_DUMP_TIMEOUT_MS",
    "UIAUTOMATOR_LAYOUT_PATH",
    "capture_android_ui_tree",
]
