"""
Android device management using ADB
"""

import asyncio
import base64
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Sequence

from loguru import logger
from pydantic import BaseModel

from ..core.types import (
    AbstractInterface, InterfaceType, UIContext, BaseElement, UINode, UITree,
    Size, Rect, NodeType
)


class AndroidElement(BaseElement):
    """Android UI element wrapper"""
    
    def __init__(self, device: 'AndroidDevice', **kwargs):
        self._device = device
        super().__init__(**kwargs)
    
    async def tap(self) -> None:
        """Tap this element"""
        try:
            center = self.center
            await self._device.tap(center[0], center[1])
        except Exception as e:
            logger.error(f"Failed to tap element: {e}")
            raise
    
    async def input_text(self, text: str) -> None:
        """Input text to this element"""
        try:
            # First tap to focus
            await self.tap()
            await asyncio.sleep(0.5)
            
            # Clear existing text
            await self._device.clear_text()
            
            # Input new text
            await self._device.input_text(text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise


# ---------------------------------------------------------------------------
# Text input helpers (upstream packages/android/src/device.ts)
# ---------------------------------------------------------------------------

IME_STRATEGY_ALWAYS_YADB = "always-yadb"
IME_STRATEGY_YADB_FOR_NON_ASCII = "yadb-for-non-ascii"
IME_STRATEGY_LEGACY = "legacy"
YADB_VERSION = "v1.1.1"
YADB_DEVICE_PATH = "/data/local/tmp/yadb"


def escape_for_shell(text: str) -> str:
    """Escape text for safe use inside single-quoted shell strings.

    In single quotes all characters are literal except ' itself; newlines are
    converted to literal \n (yadb interprets them back to real newlines).
    """
    return text.replace("'", "'\\''").replace("\n", "\\n")


def shell_escape_arg(text: str) -> str:
    """Escape a string as a single `adb shell input text` argument.

    Wraps the value in single quotes so the device shell does not interpret
    spaces, &, ;, |, $, ` etc. Internal single quotes use the '\'' sequence.
    """
    return "'" + text.replace("'", "'\\''") + "'"


def should_use_yadb_for_text(text: str) -> bool:
    """True when `adb shell input text` cannot reliably deliver this text:
    non-ASCII (Chinese etc.), format specifiers, shell-special characters, or
    mixed quotes (upstream shouldUseYadbForText)."""
    import re as _re

    has_non_ascii = any(ord(ch) >= 0x80 for ch in text)
    has_format_specifiers = bool(_re.search(r"%[a-zA-Z]", text))
    has_shell_special_chars = bool(_re.search(r"[\\`$]", text))
    has_both_quotes = '"' in text and "'" in text
    return has_non_ascii or has_format_specifiers or has_shell_special_chars or has_both_quotes



class AndroidDeviceConfig(BaseModel):
    """Android device configuration"""
    device_id: str
    adb_path: str = "adb"
    auto_dismiss_keyboard: bool = True
    use_ime: bool = True
    display_id: int = 0
    timeout: int = 30


class AndroidDevice(AbstractInterface):
    """Android device interface using ADB"""
    
    def __init__(self, device_id: str, config: Optional[AndroidDeviceConfig] = None):
        """Initialize Android device
        
        Args:
            device_id: Android device ID
            config: Device configuration
        """
        self.device_id = device_id
        self.config = config or AndroidDeviceConfig(device_id=device_id)
        self._connected = False
        self._screen_size: Optional[Size] = None
        self._yadb_pushed = False
        self._yadb_bin_path: Optional[str] = None
    
    @classmethod
    async def create(cls, device_id: Optional[str] = None) -> 'AndroidDevice':
        """Create Android device instance
        
        Args:
            device_id: Device ID, if None will use first available device
            
        Returns:
            AndroidDevice instance
        """
        if not device_id:
            devices = await cls.list_devices()
            if not devices:
                raise RuntimeError("No Android devices found")
            device_id = devices[0]
        
        device = cls(device_id)
        await device.connect()
        return device
    
    @classmethod
    async def list_devices(cls) -> List[str]:
        """List available Android devices"""
        try:
            result = await cls._run_adb_command(["devices"])
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            
            devices = []
            for line in lines:
                if '\t' in line:
                    device_id = line.split('\t')[0]
                    if device_id:
                        devices.append(device_id)
            
            return devices
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []
    
    async def connect(self) -> None:
        """Connect to Android device"""
        try:
            # Check if device is available
            devices = await self.list_devices()
            if self.device_id not in devices:
                raise RuntimeError(f"Device {self.device_id} not found")
            
            # Get screen size
            await self._get_screen_size()
            
            # Setup IME if needed
            if self.config.use_ime:
                await self._setup_ime()
            
            self._connected = True
            logger.info(f"Connected to Android device: {self.device_id}")
            
        except Exception as e:
            logger.error(f"Failed to connect to device: {e}")
            raise
    
    @property
    def interface_type(self) -> InterfaceType:
        """Get interface type"""
        return InterfaceType.ANDROID
    
    async def get_context(self) -> UIContext:
        """Get current UI context"""
        try:
            # Take screenshot
            screenshot_base64 = await self._take_screenshot()
            
            # Get UI dump
            ui_elements = await self._get_ui_elements()
            
            # Build UI tree
            tree = await self._build_ui_tree()
            
            return UIContext(
                screenshot_base64=screenshot_base64,
                size=self._screen_size or Size(width=1080, height=1920),
                content=ui_elements,
                tree=tree
            )
            
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            raise
    
    async def action_space(self) -> List[str]:
        """Get available actions"""
        return [
            "tap", "long_press", "swipe", "scroll",
            "input", "clear", "back", "home", "recent",
            "volume_up", "volume_down", "power",
            "install_app", "launch_app", "stop_app"
        ]
    
    async def tap(self, x: float, y: float) -> None:
        """Tap at coordinates"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "tap", str(int(x)), str(int(y))
            ])
        except Exception as e:
            logger.error(f"Failed to tap at ({x}, {y}): {e}")
            raise
    
    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        """Long press at coordinates"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe", 
                str(int(x)), str(int(y)), str(int(x)), str(int(y)), str(duration)
            ])
        except Exception as e:
            logger.error(f"Failed to long press at ({x}, {y}): {e}")
            raise
    
    async def swipe(
        self,
        direction_or_start_x,
        start_y=None,
        end_x=None,
        end_y=None,
        duration: int = 300,
        distance: Optional[int] = None,
    ) -> None:
        """Swipe.

        Two forms:
        - swipe(direction, distance=...) : finger-movement direction swipe
          ('up' | 'down' | 'left' | 'right'), used by the action space.
        - swipe(start_x, start_y, end_x, end_y, duration) : coordinate swipe.
        """
        try:
            if isinstance(direction_or_start_x, str):
                await self._swipe_direction(direction_or_start_x, distance)
                return
            start_x = direction_or_start_x
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(int(start_x)), str(int(start_y)),
                str(int(end_x)), str(int(end_y)), str(duration)
            ])
        except Exception as e:
            logger.error(f"Failed to swipe: {e}")
            raise

    async def _swipe_direction(
        self,
        direction: str,
        distance: Optional[int] = None,
        point: Optional[Sequence[float]] = None,
    ) -> None:
        if not self._screen_size:
            await self._get_screen_size()

        center_x = int(point[0]) if point else self._screen_size.width // 2
        center_y = int(point[1]) if point else self._screen_size.height // 2
        distance = distance or 500

        half = distance // 2
        center_x = min(
            max(center_x, half), max(half, self._screen_size.width - half)
        )
        center_y = min(
            max(center_y, half), max(half, self._screen_size.height - half)
        )

        if direction == "down":
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(center_x), str(center_y - distance // 2),
                str(center_x), str(center_y + distance // 2), "300",
            ])
        elif direction == "up":
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(center_x), str(center_y + distance // 2),
                str(center_x), str(center_y - distance // 2), "300",
            ])
        elif direction == "left":
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(center_x + distance // 2), str(center_y),
                str(center_x - distance // 2), str(center_y), "300",
            ])
        elif direction == "right":
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(center_x - distance // 2), str(center_y),
                str(center_x + distance // 2), str(center_y), "300",
            ])
        else:
            raise ValueError(f"Invalid swipe direction: {direction}")

    async def drag_and_drop(self, from_point, to_point, duration: int = 1000) -> None:
        """Drag an element from one point to another (upstream dragPoint)."""
        try:
            from_x, from_y = from_point
            to_x, to_y = to_point
            await self.swipe(
                from_x, from_y, to_x, to_y, duration=duration
            )
        except Exception as e:
            logger.error(f"Failed to drag from {from_point} to {to_point}: {e}")
            raise

    async def input_text(self, text: str) -> None:
        r"""Input text.

        Uses the upstream IME strategy (MIDSCENE_ANDROID_IME_STRATEGY):
        'yadb-for-non-ascii' (default) routes text that `adb shell input text`
        cannot deliver reliably (non-ASCII, % specifiers, \ ` $, mixed quotes)
        through the Yadb tool; 'always-yadb' always uses Yadb; 'legacy' always
        uses `input text` with proper shell escaping.
        """
        await self._type_text(text)

    async def _type_text(self, text: str) -> None:
        """Type text following the resolved IME strategy (upstream typeText)."""
        if not text:
            return
        import os as _os

        strategy = (
            _os.environ.get("MIDSCENE_ANDROID_IME_STRATEGY")
            or IME_STRATEGY_YADB_FOR_NON_ASCII
        )
        if strategy not in (
            IME_STRATEGY_ALWAYS_YADB,
            IME_STRATEGY_YADB_FOR_NON_ASCII,
            IME_STRATEGY_LEGACY,
        ):
            logger.warning(
                f"Unknown MIDSCENE_ANDROID_IME_STRATEGY {strategy!r}, "
                f"falling back to {IME_STRATEGY_YADB_FOR_NON_ASCII}"
            )
            strategy = IME_STRATEGY_YADB_FOR_NON_ASCII

        needs_yadb = strategy == IME_STRATEGY_ALWAYS_YADB or (
            strategy == IME_STRATEGY_YADB_FOR_NON_ASCII
            and should_use_yadb_for_text(text)
        )

        try:
            if needs_yadb:
                await self._exec_yadb_raw(text)
            else:
                await self._shell_input_text(text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise

    async def _shell_input_text(self, text: str) -> None:
        """`adb shell input text` with proper shell escaping; input text cannot
        handle newlines, so segments are split and Enter is pressed between
        them (upstream shellInputText)."""
        segments = text.split("\n")
        for index, segment in enumerate(segments):
            if segment:
                await self._run_adb_command([
                    "-s", self.device_id, "shell",
                    "input", "text", shell_escape_arg(segment),
                ])
            if index < len(segments) - 1:
                await self.key_event("KEYCODE_ENTER")

    def _resolve_yadb_bin_path(self) -> str:
        """Local Yadb binary path: <MIDSCENE_RUN_DIR>/bin/yadb."""
        from ..core.ai_model.env_config import get_midscene_run_dir

        if self._yadb_bin_path is None:
            self._yadb_bin_path = str(
                Path(get_midscene_run_dir("bin")) / "yadb"
            )
        return self._yadb_bin_path

    async def _ensure_yadb(self) -> None:
        """Download (once) and push the Yadb tool to the device."""
        if self._yadb_pushed:
            return
        bin_path = Path(self._resolve_yadb_bin_path())
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        if not bin_path.exists():
            import httpx

            url = (
                "https://github.com/ysbing/YADB/releases/download/"
                f"{YADB_VERSION}/yadb"
            )
            logger.info(f"Downloading Yadb tool from {url} ...")
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                response = await client.get(url)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Failed to download Yadb tool ({response.status_code}). "
                    "Chinese/special-character input requires Yadb; place the "
                    "binary at " + str(bin_path) + " manually, or set "
                    "MIDSCENE_ANDROID_IME_STRATEGY=legacy."
                )
            bin_path.write_bytes(response.content)
            bin_path.chmod(0o755)
        await self._run_adb_command(["push", str(bin_path), YADB_DEVICE_PATH])
        self._yadb_pushed = True

    async def _exec_yadb_raw(self, keyboard_content: str) -> None:
        """Inject text through the Yadb app_process tool."""
        try:
            await self._ensure_yadb()
        except Exception as e:
            logger.warning(
                f"Yadb unavailable ({e}); falling back to `input text`."
            )
            await self._shell_input_text(keyboard_content)
            return
        await self._run_adb_command([
            "-s", self.device_id, "shell",
            "app_process",
            f"-Djava.class.path={YADB_DEVICE_PATH}",
            YADB_DEVICE_PATH,
            "com.ysbing.yadb.Main",
            "-keyboard",
            "'" + escape_for_shell(keyboard_content) + "'",
        ])

    async def run_adb_shell(self, command: str, timeout: Optional[float] = None) -> str:
        """Run an arbitrary adb shell command (RunAdbShell action).

        `timeout` is accepted for upstream compatibility; the underlying adb
        client applies its own command timeout.
        """
        output = await self._run_adb_command(["-s", self.device_id, "shell", command])
        return output if isinstance(output, str) else ""
    
    async def clear_text(self) -> None:
        """Clear text in focused field"""
        try:
            # Select all and delete
            await self.key_event("KEYCODE_MOVE_END")
            await self.key_event("KEYCODE_SHIFT_LEFT")
            await self.key_event("KEYCODE_MOVE_HOME")
            await self.key_event("KEYCODE_DEL")
        except Exception as e:
            logger.error(f"Failed to clear text: {e}")
            raise
    
    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
        point: Optional[Sequence[float]] = None,
        scroll_type: Optional[str] = None,
    ) -> None:
        """Scroll in direction.

        `point` is the gesture center (usually a located region). Scroll
        directions describe the content to reveal, i.e. the opposite of the
        finger movement used by swipe.
        """
        try:
            finger_direction = {
                "down": "up",
                "up": "down",
                "left": "right",
                "right": "left",
            }.get(direction)
            if finger_direction is None:
                raise ValueError(f"Invalid scroll direction: {direction}")

            repeats = 10 if (scroll_type or "").startswith("scrollTo") else 1
            if repeats > 1:
                if not self._screen_size:
                    await self._get_screen_size()
                axis = (
                    self._screen_size.height
                    if direction in ("up", "down")
                    else self._screen_size.width
                )
                distance = int(axis * 0.8)
            for _ in range(repeats):
                await self._swipe_direction(finger_direction, distance, point=point)

        except Exception as e:
            logger.error(f"Failed to scroll {direction}: {e}")
            raise
    
    async def clear_input(self) -> None:
        """Clear text in focused field (alias of clear_text)"""
        await self.clear_text()

    async def replace_input(self, text: str) -> None:
        """Replace the content of the focused field"""
        await self.clear_text()
        await self.input_text(text)

    async def keyboard_press(self, key: str) -> None:
        """Press a key by name, e.g. 'Enter', 'Tab', 'Backspace', 'Control+A'."""
        key_map = {
            "ENTER": "KEYCODE_ENTER",
            "TAB": "KEYCODE_TAB",
            "BACKSPACE": "KEYCODE_DEL",
            "DELETE": "KEYCODE_FORWARD_DEL",
            "ESCAPE": "KEYCODE_ESCAPE",
            "HOME": "KEYCODE_HOME",
            "ARROWUP": "KEYCODE_DPAD_UP",
            "ARROWDOWN": "KEYCODE_DPAD_DOWN",
            "ARROWLEFT": "KEYCODE_DPAD_LEFT",
            "ARROWRIGHT": "KEYCODE_DPAD_RIGHT",
        }
        # combinations like 'Control+A' fall back to the bare key
        bare_key = key.split("+")[-1].upper()
        key_code = key_map.get(bare_key)
        if key_code:
            await self.key_event(key_code)
        elif bare_key.isalnum() and len(bare_key) == 1:
            await self.key_event(f"KEYCODE_{bare_key.upper()}")
        else:
            raise ValueError(f"Unsupported key for Android: {key}")

    async def key_event(self, key_code: str) -> None:
        """Send key event"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "keyevent", key_code
            ])
        except Exception as e:
            logger.error(f"Failed to send key event {key_code}: {e}")
            raise
    
    async def back(self) -> None:
        """Press back button"""
        await self.key_event("KEYCODE_BACK")
    
    async def home(self) -> None:
        """Press home button"""
        await self.key_event("KEYCODE_HOME")
    
    async def recent(self) -> None:
        """Press recent apps button"""
        await self.key_event("KEYCODE_APP_SWITCH")
    
    async def install_app(self, apk_path: str) -> None:
        """Install APK"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "install", apk_path
            ])
        except Exception as e:
            logger.error(f"Failed to install app: {e}")
            raise
    
    async def launch_app(self, package_name: str, activity: Optional[str] = None) -> None:
        """Launch app"""
        try:
            if activity:
                component = f"{package_name}/{activity}"
            else:
                component = package_name
            
            await self._run_adb_command([
                "-s", self.device_id, "shell", "am", "start", "-n", component
            ])
        except Exception as e:
            logger.error(f"Failed to launch app: {e}")
            raise
    
    async def stop_app(self, package_name: str) -> None:
        """Stop app"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "shell", "am", "force-stop", package_name
            ])
        except Exception as e:
            logger.error(f"Failed to stop app: {e}")
            raise
    
    async def _take_screenshot(self) -> str:
        """Take screenshot and return base64 string"""
        try:
            # Take screenshot using screencap
            result = await self._run_adb_command([
                "-s", self.device_id, "shell", "screencap", "-p"
            ], capture_output=True)
            
            # Convert bytes to base64
            screenshot_base64 = base64.b64encode(result.stdout).decode('utf-8')
            
            return screenshot_base64
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise
    
    async def _get_ui_elements(self) -> List[AndroidElement]:
        """Get UI elements using uiautomator dump"""
        try:
            # Get UI dump
            await self._run_adb_command([
                "-s", self.device_id, "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"
            ])
            
            # Pull dump file
            result = await self._run_adb_command([
                "-s", self.device_id, "shell", "cat", "/sdcard/ui_dump.xml"
            ], capture_output=True)
            
            xml_content = result.stdout.decode('utf-8')
            
            # Parse XML
            root = ET.fromstring(xml_content)
            elements = []
            
            def parse_node(node, index=0):
                if node.tag == "node":
                    bounds = node.get("bounds", "")
                    if bounds:
                        # Parse bounds [x1,y1][x2,y2]
                        coords = bounds.replace('][', ',').replace('[', '').replace(']', '').split(',')
                        if len(coords) == 4:
                            x1, y1, x2, y2 = map(int, coords)
                            
                            rect = Rect(
                                left=x1, top=y1,
                                width=x2-x1, height=y2-y1
                            )
                            
                            content = node.get("text", "") or node.get("content-desc", "")
                            class_name = node.get("class", "")
                            
                            # Determine node type
                            node_type = self._get_android_node_type(class_name)
                            
                            element = AndroidElement(
                                device=self,
                                id=f"element_{index}",
                                content=content,
                                rect=rect,
                                center=(x1 + (x2-x1)/2, y1 + (y2-y1)/2),
                                node_type=node_type,
                                attributes={
                                    "class": class_name,
                                    "package": node.get("package", ""),
                                    "clickable": node.get("clickable", "false") == "true",
                                    "enabled": node.get("enabled", "false") == "true",
                                    "focused": node.get("focused", "false") == "true",
                                    "selected": node.get("selected", "false") == "true",
                                },
                                is_visible=rect.width > 0 and rect.height > 0
                            )
                            
                            if element.is_visible:
                                elements.append(element)
                
                # Process children
                for child in node:
                    parse_node(child, len(elements))
            
            parse_node(root)
            return elements
            
        except Exception as e:
            logger.error(f"Failed to get UI elements: {e}")
            return []
    
    def _get_android_node_type(self, class_name: str) -> NodeType:
        """Determine node type from Android class name"""
        class_name = class_name.lower()
        
        if "button" in class_name:
            return NodeType.BUTTON
        elif "edittext" in class_name or "textfield" in class_name:
            return NodeType.INPUT
        elif "textview" in class_name or "text" in class_name:
            return NodeType.TEXT
        elif "imageview" in class_name or "image" in class_name:
            return NodeType.IMAGE
        elif "linearlayout" in class_name or "relativelayout" in class_name or "framelayout" in class_name:
            return NodeType.CONTAINER
        else:
            return NodeType.OTHER
    
    async def _build_ui_tree(self) -> UITree:
        """Build UI tree structure"""
        # Simplified implementation - return minimal tree
        root_node = UINode(
            id="root",
            content="",
            rect=Rect(left=0, top=0, width=self._screen_size.width if self._screen_size else 1080, 
                     height=self._screen_size.height if self._screen_size else 1920),
            center=(540, 960),
            node_type=NodeType.CONTAINER,
            attributes={},
            is_visible=True,
            children=[]
        )
        
        return UITree(node=root_node, children=[])
    
    async def _get_screen_size(self) -> None:
        """Get device screen size"""
        try:
            result = await self._run_adb_command([
                "-s", self.device_id, "shell", "wm", "size"
            ], capture_output=True)
            
            output = result.stdout.decode('utf-8').strip()
            # Parse output like "Physical size: 1080x1920"
            if ":" in output:
                size_str = output.split(":")[-1].strip()
                if "x" in size_str:
                    width, height = map(int, size_str.split("x"))
                    self._screen_size = Size(width=width, height=height)
                    return
            
            # Fallback
            self._screen_size = Size(width=1080, height=1920)
            
        except Exception as e:
            logger.warning(f"Failed to get screen size: {e}")
            self._screen_size = Size(width=1080, height=1920)
    
    async def _setup_ime(self) -> None:
        """No IME setup required: text injection uses the Yadb tool
        (app_process) or `input text`, neither of which needs an IME."""
        try:
            pass
        except Exception as e:
            logger.warning(f"Failed to setup IME: {e}")
    
    @staticmethod
    async def _run_adb_command(
        args: List[str], 
        capture_output: bool = False,
        timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """Run ADB command"""
        try:
            if capture_output:
                result = await asyncio.create_subprocess_exec(
                    "adb", *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=timeout)
                
                return subprocess.CompletedProcess(
                    args=["adb"] + args,
                    returncode=result.returncode,
                    stdout=stdout,
                    stderr=stderr
                )
            else:
                result = await asyncio.create_subprocess_exec("adb", *args)
                returncode = await asyncio.wait_for(result.wait(), timeout=timeout)
                
                return subprocess.CompletedProcess(
                    args=["adb"] + args,
                    returncode=returncode
                )
                
        except asyncio.TimeoutError:
            raise TimeoutError(f"ADB command timeout: {args}")
        except Exception as e:
            logger.error(f"ADB command failed: {args}, error: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from device"""
        self._connected = False
        logger.info(f"Disconnected from device: {self.device_id}")
    
    def __del__(self):
        """Cleanup on deletion"""
        if self._connected:
            # Note: Can't use async in __del__, this is just for cleanup tracking
            logger.debug(f"Device {self.device_id} being garbage collected")