"""HDC (HarmonyOS Device Connector) client.

Synced from upstream packages/harmony/src/hdc.ts (v1.17.4). Every device
operation goes through the hdc CLI + the on-device uitest service.
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

UI_INPUT_SPEED_RANGE = {"min": 200, "max": 40000}
SUPPORTED_STRING_KEY_EVENTS = {"Back", "Home", "Power"}
NUMERIC_KEY_EVENT_PATTERN = re.compile(r"^\d+$")
UI_INPUT_ERROR_PATTERN = re.compile(
    r"(?:(?:Invalid parameters|Missing parameter|Too many parameters)\.?|"
    r"Please confirm that the coordinate values are correct\.?)",
    re.IGNORECASE,
)


def round_ui_coordinate(value: float, label: str = "coordinate") -> int:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"Invalid HarmonyOS uiInput {label}: {value!r}")
    return int(round(value))


def round_ui_input_speed(speed: float, operation: str = "swipe") -> int:
    if speed != speed or speed in (float("inf"), float("-inf")):
        raise ValueError(f"Invalid HarmonyOS uiInput speed for {operation}: {speed!r}")
    return int(round(speed))


def resolve_hdc_path(hdc_path: Optional[str] = None) -> str:
    """Resolve the hdc binary (upstream resolveHdcPath):
    explicit > HDC_HOME > common install paths > PATH."""
    if hdc_path:
        return hdc_path
    env_home = os.environ.get("HDC_HOME")
    if env_home:
        return f"{env_home}/hdc"
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
    common_paths = [
        f"{home}/Library/HarmonyOS/next/command-line-tools/sdk/default/openharmony/toolchains/hdc",
        f"{home}/Library/HarmonyOS/sdk/hmscore/3.1.0/toolchains/hdc",
        f"{home}/harmonyos/command-line-tools/sdk/default/openharmony/toolchains/hdc",
    ]
    for candidate in common_paths:
        try:
            if Path(candidate).exists() and os.access(candidate, os.X_OK):
                logger.debug(f"Found HDC at: {candidate}")
                return candidate
        except OSError:
            continue
    return "hdc"


class HdcClient:
    """Serialize hdc CLI invocations against one device (upstream HdcClient)."""

    def __init__(
        self,
        device_id: str = "",
        hdc_path: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.hdc_path = resolve_hdc_path(hdc_path)
        self.device_id = device_id or ""
        self.timeout = timeout
        self._exec_lock = asyncio.Lock()
        self._launch_ability_cache: Dict[str, Dict[str, str]] = {}

    def _build_args(self, args: List[str]) -> List[str]:
        if self.device_id:
            return ["-t", self.device_id, *args]
        return list(args)

    async def exec(self, *args: str) -> str:
        """Run one hdc command; serialized to prevent concurrent processes
        competing for the device connection (upstream execMutex)."""
        async with self._exec_lock:
            full_args = self._build_args(list(args))
            logger.debug(f"hdc {' '.join(full_args)}")
            process = await asyncio.create_subprocess_exec(
                self.hdc_path,
                *full_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError(
                    f"HDC command failed: hdc {' '.join(full_args)}: timed out "
                    f"after {self.timeout}s"
                )

            stdout_text = stdout.decode("utf-8", "replace")
            stderr_text = stderr.decode("utf-8", "replace")
            if stderr_text.strip():
                logger.debug(f"hdc stderr: {stderr_text.strip()}")
            if process.returncode != 0:
                # hdc shell may exit non-zero after producing valid output
                # (hang-kill on Windows); accept stdout when present.
                if stdout_text.strip():
                    return stdout_text
                raise RuntimeError(
                    f"HDC command failed: hdc {' '.join(full_args)}: "
                    f"{stderr_text.strip() or f'exit code {process.returncode}'}"
                )
            return stdout_text

    async def shell(self, command: str) -> str:
        return await self.exec("shell", command)

    async def file_send(self, local_path: str, remote_path: str) -> None:
        await self.exec("file", "send", local_path, remote_path)

    async def file_recv(self, remote_path: str, local_path: str) -> None:
        await self.exec("file", "recv", remote_path, local_path)

    # -- assertions ----------------------------------------------------------

    @staticmethod
    def _assert_ui_input_succeeded(operation: str, output: str, detail: str = "") -> None:
        match = UI_INPUT_ERROR_PATTERN.search(output)
        if not match:
            return
        detail_text = f" for {detail}" if detail else ""
        raise RuntimeError(
            f"HDC uiInput {operation} failed{detail_text}: {match.group(0)}"
        )

    async def _run_ui_input(self, operation: str, args: str, detail: str = "") -> None:
        output = await self.shell(f"uitest uiInput {operation} {args}")
        self._assert_ui_input_succeeded(operation, output, detail)

    # -- screenshots ---------------------------------------------------------

    async def screenshot(self, remote_path: str) -> str:
        return await self.shell(f"snapshot_display -f {remote_path}")

    # -- pointer operations ---------------------------------------------------

    async def click(self, x: float, y: float) -> None:
        await self._run_ui_input(
            "click", f"{round_ui_coordinate(x)} {round_ui_coordinate(y)}"
        )

    async def double_click(self, x: float, y: float) -> None:
        await self._run_ui_input(
            "doubleClick", f"{round_ui_coordinate(x)} {round_ui_coordinate(y)}"
        )

    async def long_click(self, x: float, y: float) -> None:
        await self._run_ui_input(
            "longClick", f"{round_ui_coordinate(x)} {round_ui_coordinate(y)}"
        )

    def _pointer_args(
        self, from_x: float, from_y: float, to_x: float, to_y: float,
        speed: Optional[float], operation: str,
    ) -> str:
        args = [
            str(round_ui_coordinate(from_x)),
            str(round_ui_coordinate(from_y)),
            str(round_ui_coordinate(to_x)),
            str(round_ui_coordinate(to_y)),
        ]
        if speed is not None:
            args.append(str(round_ui_input_speed(speed, operation)))
        return " ".join(args)

    async def swipe(
        self, from_x: float, from_y: float, to_x: float, to_y: float,
        speed: Optional[float] = None,
    ) -> None:
        await self._run_ui_input(
            "swipe", self._pointer_args(from_x, from_y, to_x, to_y, speed, "swipe")
        )

    async def fling(
        self, from_x: float, from_y: float, to_x: float, to_y: float,
        speed: Optional[float] = None,
    ) -> None:
        await self._run_ui_input(
            "fling", self._pointer_args(from_x, from_y, to_x, to_y, speed, "fling")
        )

    async def drag(
        self, from_x: float, from_y: float, to_x: float, to_y: float,
        speed: Optional[float] = None,
    ) -> None:
        await self._run_ui_input(
            "drag", self._pointer_args(from_x, from_y, to_x, to_y, speed, "drag")
        )

    # -- text / keys -----------------------------------------------------------

    async def input_text(self, x: float, y: float, text: str) -> None:
        escaped = text.replace("'", "'\\''")
        await self._run_ui_input(
            "inputText",
            f"{round_ui_coordinate(x)} {round_ui_coordinate(y)} '{escaped}'",
            detail=text[:20],
        )

    async def key_event(self, *keys: str) -> None:
        if not 1 <= len(keys) <= 3:
            raise RuntimeError("HDC keyEvent requires between 1 and 3 keys")
        if len(keys) > 1 and any(k in SUPPORTED_STRING_KEY_EVENTS for k in keys):
            raise RuntimeError("HDC system key events cannot be combined")
        for key in keys:
            if key not in SUPPORTED_STRING_KEY_EVENTS and not NUMERIC_KEY_EVENT_PATTERN.match(key):
                raise RuntimeError(f"Invalid HDC key event: {key}")
        joined = " ".join(keys)
        await self._run_ui_input("keyEvent", joined, joined)

    async def clear_text_field(self) -> None:
        """Select all in the focused field (Ctrl+A), then delete
        (upstream clearTextField: codes 2072=Control 2017=A, 2055=Delete)."""
        output = await self.shell(
            "uitest uiInput keyEvent 2072 2017;uitest uiInput keyEvent 2055"
        )
        self._assert_ui_input_succeeded("clearTextField", output)

    # -- app management ---------------------------------------------------------

    async def start_ability(
        self, bundle_name: str, ability_name: str, module_name: Optional[str] = None
    ) -> None:
        module_arg = f" -m {module_name}" if module_name else ""
        output = await self.shell(
            f"aa start -a {ability_name} -b {bundle_name}{module_arg}"
        )
        if "error:" in output:
            raise RuntimeError(
                f"Failed to start {bundle_name}/{ability_name}: {output.strip()}"
            )

    async def launch(self, uri: str) -> None:
        """Launch by bundle name (resolve entry ability via bm dump) or URI."""
        if "://" in uri:
            await self.shell(f"aa start -U {uri}")
            return
        target = self._launch_ability_cache.get(uri)
        if target is None:
            target = await self._query_launch_ability(uri)
            self._launch_ability_cache[uri] = target
        await self.start_ability(
            target["bundleName"], target["abilityName"], target.get("moduleName")
        )

    async def _query_launch_ability(self, bundle_name: str) -> Dict[str, str]:
        """Resolve the launcher ability from `bm dump` (compact upstream
        queryLaunchAbility)."""
        output = await self.shell(f"bm dump -n {bundle_name}")
        if "error" in output.lower() and "abilityInfos" not in output:
            raise RuntimeError(
                f"Failed to query bundle info for {bundle_name}: {output.strip()[:300]}"
            )
        ability_match = re.search(r'"name"\s*:\s*"([^"]+)"', output)
        ability = ability_match.group(1) if ability_match else "EntryAbility"
        return {"bundleName": bundle_name, "abilityName": ability}

    async def force_stop(self, bundle_name: str) -> None:
        output = await self.shell(f"aa force-stop {bundle_name}")
        if "error:" in output:
            raise RuntimeError(
                f"Failed to force stop {bundle_name}: {output.strip()}"
            )

    # -- device info ------------------------------------------------------------

    async def get_screen_info(self) -> Dict[str, int]:
        """Read the active display render size (foldable-aware; upstream
        getScreenInfo)."""
        stdout = await self.shell("hidumper -s RenderService -a screen")
        render_dimension_pattern = (
            r"render\s+(?:size|resolution)\s*[:=]\s*(\d{3,5})x(\d{3,5})"
        )
        fold_match = re.search(
            r"foldScreenId:(\d+),\s*isConnected:\d+,\s*isPowerOn:1", stdout
        )
        if fold_match:
            screen_regex = re.compile(
                rf"screen\[\d+\]:\s*id={fold_match.group(1)},.*?{render_dimension_pattern}",
                re.DOTALL,
            )
            screen_match = screen_regex.search(stdout)
            if screen_match:
                return {
                    "width": int(screen_match.group(1)),
                    "height": int(screen_match.group(2)),
                }
        render_match = re.search(render_dimension_pattern, stdout)
        if render_match:
            return {"width": int(render_match.group(1)), "height": int(render_match.group(2))}

        display_stdout = await self.shell("hidumper -s DisplayManagerService -a")
        display_match = re.search(r"activeModes.*?(\d{3,5}),\s*(\d{3,5})", display_stdout, re.DOTALL)
        if display_match:
            return {"width": int(display_match.group(1)), "height": int(display_match.group(2))}
        raise RuntimeError(
            f"Failed to get screen size from HDC. RenderService output: {stdout[:500]}"
        )

    async def list_targets(self) -> List[str]:
        stdout = await self.exec("list", "targets")
        return [
            line.strip()
            for line in stdout.strip().splitlines()
            if line.strip() and not line.strip().startswith("[")
        ]

