"""Shared types for Midscene Python (upstream packages/shared/src/types/index.ts).

These definitions used to live in ``midscene.core.types``. They now live in
the shared package so platform, core, and CLI layers can depend on the
type vocabulary without importing core runtime modules.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Generic,
    Optional,
    TypeVar,
)

from pydantic import BaseModel

# Type variables
ElementType = TypeVar("ElementType", bound="BaseElement")
T = TypeVar("T")


class InterfaceType(str, Enum):
    """Interface type enumeration"""

    WEB = "web"
    ANDROID = "android"
    COMPUTER = "computer"
    HARMONY = "harmony"
    IOS = "ios"


class NodeType(str, Enum):
    """UI Node type enumeration"""

    CONTAINER = "container"
    TEXT = "text"
    INPUT = "input"
    BUTTON = "button"
    IMAGE = "image"
    LINK = "link"
    OTHER = "other"


@dataclass
class Point:
    """2D Point representation"""

    x: float
    y: float


@dataclass
class Size:
    """Size representation"""

    width: float
    height: float


@dataclass
class Rect:
    """Rectangle representation"""

    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def center(self) -> Point:
        return Point(x=self.left + self.width / 2, y=self.top + self.height / 2)


class BaseElement(BaseModel):
    """Base UI element interface"""

    id: str
    content: str
    rect: Rect
    center: tuple[float, float]
    node_type: NodeType = NodeType.OTHER
    attributes: dict[str, Any] = field(default_factory=dict)
    is_visible: bool = True
    xpaths: list[str] | None = None

    async def tap(self) -> None:
        """Tap/click this element"""
        raise NotImplementedError

    async def input_text(self, text: str) -> None:
        """Input text to this element"""
        raise NotImplementedError


class UINode(BaseModel):
    """UI tree node representation"""

    id: str
    content: str
    rect: Rect
    center: tuple[float, float]
    node_type: NodeType
    attributes: dict[str, Any] = field(default_factory=dict)
    is_visible: bool = True
    children: list["UINode"] = field(default_factory=list)


class UITree(BaseModel):
    """UI tree representation"""

    node: UINode
    children: list["UITree"] = field(default_factory=list)


class UIContext(BaseModel, Generic[ElementType]):
    """UI context containing screenshot and element information"""

    screenshot_base64: str
    size: Size
    content: list[ElementType]
    tree: UITree
    # Screenshot coordinates -> logical viewport coordinates factor
    # (upstream shrunkShotToLogicalRatio = dpr / screenshotShrinkFactor).
    shrunk_shot_to_logical_ratio: float = 1.0
    # Optional consecutive screenshots over a time window (UI observation
    # frames, earliest first; upstream screenshotSequence)
    screenshot_sequence: list[str] | None = None


class AIUsageInfo(BaseModel):
    """AI usage information"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None


class LocateResult(BaseModel):
    """Element locate result.

    After the upstream sync, locate is coordinate-based: `center` is the
    (x, y) click point and `rect` the element bounding box when available.
    `element` is kept for backward compatibility and stays None in the
    pure-vision flow.
    """

    element: BaseElement | None = None
    rect: Rect | None = None
    center: list[float] | None = None
    description: str | None = None
    raw_response: str | None = None


class ExecutionResult(BaseModel, Generic[T]):
    """Generic execution result"""

    success: bool = True
    data: Any | None = None
    error: str | None = None
    usage: AIUsageInfo | None = None


class AssertResult(BaseModel):
    """Assertion result"""

    passed: bool
    thought: str = ""
    message: str = ""


# Type aliases
TUserPrompt = str | dict[str, Any]
ElementById = Callable[[str], BaseElement | None]
OnTaskStartTip = Callable[[str], None | Awaitable[None]]


class AbortError(RuntimeError):
    """Raised when an operation observes an aborted signal."""


class AbortSignal:
    """Python counterpart of the upstream `AbortSignal` used by aiAct.

    `asyncio.Event` / `threading.Event` instances are accepted as well (see
    `midscene.core.agent.agent`), so callers can drive cancellation with either API.

    Listeners mirror the upstream DOM API used by the workflow engine
    (`addEventListener('abort', ...)` / `removeEventListener`). They run
    synchronously inside `abort()`; abort listeners must not block.
    """

    def __init__(self) -> None:
        import threading

        self._aborted = False
        self._reason: Any = None
        self._listeners: list[Any] = []
        self._lock = threading.RLock()

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def abort(self, reason: Any = None) -> None:
        with self._lock:
            if self._aborted:
                return
            self._aborted = True
            self._reason = reason
            listeners = list(self._listeners)
            self._listeners = []
        for callback in listeners:
            callback()

    def add_event_listener(self, event: str, callback: Any, once: bool = False) -> None:
        if event != "abort":
            raise ValueError(f"Unsupported AbortSignal event: {event}")
        with self._lock:
            if self._aborted:
                aborted = True
            else:
                aborted = False
                if once:

                    def _once() -> None:
                        self.remove_event_listener("abort", _once)
                        callback()

                    self._listeners.append(_once)
                else:
                    self._listeners.append(callback)
        if aborted:
            callback()

    def remove_event_listener(self, event: str, callback: Any) -> None:
        if event != "abort":
            return
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not callback]

    # Upstream naming aliases -------------------------------------------
    def addEventListener(self, event: str, callback: Any, once: bool = False) -> None:  # noqa: N802
        self.add_event_listener(event, callback, once)

    def removeEventListener(self, event: str, callback: Any) -> None:  # noqa: N802
        self.remove_event_listener(event, callback)

    def throw_if_aborted(self) -> None:
        if self._aborted:
            raise AbortError(
                "Operation interrupted by an external abort signal.\n"
                f"Reason: {self._reason or 'signal already aborted'}"
            )


@dataclass
class FileChooserHandler:
    """Handle passed to a file chooser listener (upstream FileChooserHandler)."""

    accept: Callable[[list[str]], Awaitable[None]]


@dataclass
class FileChooserRegistration:
    """Result of registering a file chooser listener."""

    dispose: Callable[[], None]
    get_error: Callable[[], BaseException | None]


# Abstract interface for device/platform implementations
class AbstractInterface(ABC):
    """Abstract interface for platform implementations.

    tap/input_text/scroll are required; the remaining primitives power the
    extended planning action space and raise NotImplementedError by default.
    """

    @property
    @abstractmethod
    def interface_type(self) -> InterfaceType:
        """Get interface type"""
        pass

    @abstractmethod
    async def get_context(self) -> UIContext:
        """Get current UI context"""
        pass

    async def screenshot_base64(self) -> str:
        """Capture the current screen as base64 (upstream screenshotBase64)."""
        raise NotImplementedError(
            "screenshot_base64 is not supported on this interface"
        )

    async def size(self) -> Size:
        """Current screen size (upstream size()).

        Interfaces that can capture a context derive it from there; platforms
        with a cheaper probe override this method.
        """
        context = await self.get_context()
        return context.size

    @abstractmethod
    async def action_space(self) -> list[str]:
        """Get available actions"""
        pass

    @abstractmethod
    async def tap(self, x: float, y: float) -> None:
        """Tap at coordinates"""
        pass

    @abstractmethod
    async def input_text(self, text: str) -> None:
        """Input text"""
        pass

    @abstractmethod
    async def scroll(
        self, direction: str, distance: int | None = None, **kwargs
    ) -> None:
        """Scroll in direction"""
        pass

    # Optional primitives for the extended action space ---------------------

    async def right_click(self, x: float, y: float) -> None:
        raise NotImplementedError("right_click is not supported on this interface")

    async def middle_click(self, x: float, y: float) -> None:
        raise NotImplementedError("middle_click is not supported on this interface")

    async def double_click(self, x: float, y: float) -> None:
        raise NotImplementedError("double_click is not supported on this interface")

    async def hover(self, x: float, y: float) -> None:
        raise NotImplementedError("hover is not supported on this interface")

    async def keyboard_press(self, key: str) -> None:
        raise NotImplementedError("keyboard_press is not supported on this interface")

    async def clear_input(self) -> None:
        raise NotImplementedError("clear_input is not supported on this interface")

    async def replace_input(self, text: str) -> None:
        raise NotImplementedError("replace_input is not supported on this interface")

    async def swipe(self, direction: str, distance: int | None = None) -> None:
        raise NotImplementedError("swipe is not supported on this interface")

    async def swipe_points(
        self,
        start: list[float],
        end: list[float],
        duration: int | None = None,
    ) -> None:
        """Swipe from one logical point to another (upstream swipe(start, end))."""
        raise NotImplementedError("swipe_points is not supported on this interface")

    async def pull_gesture(
        self,
        direction: str,
        start_point: list[float] | None = None,
        distance: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Pull-to-refresh / pull-up gesture (upstream Android PullGesture)."""
        raise NotImplementedError("pull_gesture is not supported on this interface")

    async def pinch(
        self,
        center: list[float],
        start_distance: float,
        end_distance: float,
        duration: int | None = None,
    ) -> None:
        """Two-finger pinch around `center` (upstream pinch primitive)."""
        raise NotImplementedError("pinch is not supported on this interface")

    async def drag_and_drop(self, from_point, to_point) -> None:
        raise NotImplementedError("drag_and_drop is not supported on this interface")

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        raise NotImplementedError("long_press is not supported on this interface")

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        raise NotImplementedError("cursor_move is not supported on this interface")

    # Browser navigation primitives (upstream AbstractWebPage navigate/reload/
    # goBack/goForward; only interfaces with a history expose them).
    async def navigate_to(self, url: str) -> None:
        raise NotImplementedError("navigate_to is not supported on this interface")

    async def reload(self) -> None:
        raise NotImplementedError("reload is not supported on this interface")

    async def go_back(self) -> None:
        raise NotImplementedError("go_back is not supported on this interface")

    async def go_forward(self) -> None:
        raise NotImplementedError("go_forward is not supported on this interface")

    async def get_device_time(self) -> str:
        """Device-local wall clock, used by planning feedback messages."""
        raise NotImplementedError("get_device_time is not supported on this interface")

    async def register_file_chooser_listener(
        self, handler: Callable[[FileChooserHandler], Awaitable[None]]
    ) -> FileChooserRegistration:
        """Listen for file chooser dialogs and let `handler` accept files."""
        raise NotImplementedError(
            "register_file_chooser_listener is not supported on this interface"
        )

    # Optional element locate-cache hooks -----------------------------------

    async def cache_feature_for_point(
        self, center: list[float], options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build a serializable feature for the element at `center`.

        The feature is persisted in the locate cache and must be resolvable by
        `rect_matches_cache_feature` on a later run (upstream
        `interface.cacheFeatureForPoint`).
        """
        raise NotImplementedError(
            "cache_feature_for_point is not supported on this interface"
        )

    async def rect_matches_cache_feature(self, feature: dict[str, Any]) -> Rect | None:
        """Resolve a cached feature back to a rect; raise when it is stale."""
        raise NotImplementedError(
            "rect_matches_cache_feature is not supported on this interface"
        )


def supports_interface_extension(interface: Any, method_name: str) -> bool:
    """True when the concrete interface overrides the base-class stub."""
    base = getattr(AbstractInterface, method_name, None)
    implementation = getattr(type(interface), method_name, None)
    return implementation is not None and implementation is not base


class InsightAction(str, Enum):
    """Insight action types"""

    LOCATE = "locate"
    EXTRACT = "extract"
    ASSERT = "assert"


@dataclass
class LocateOption:
    """Locate operation options"""

    prompt: TUserPrompt | None = None
    deep_think: bool = False
    cacheable: bool = True
    xpath: str | None = None
    ui_context: UIContext | None = None


@dataclass
class ExtractOption:
    """Extract operation options"""

    dom_included: bool | str = False  # False, True, or 'visible-only'
    screenshot_included: bool = True
    return_thought: bool = False
    is_wait_for_assert: bool = False
    do_not_throw_error: bool = False


class ScrollParam(BaseModel):
    """Scroll parameters"""

    direction: str  # 'down', 'up', 'left', 'right'
    scroll_type: str  # 'once', 'untilBottom', 'untilTop', 'untilLeft', 'untilRight'
    distance: int | None = None  # distance in pixels


__all__ = [
    "AbortError",
    "AbortSignal",
    "AbstractInterface",
    "AIUsageInfo",
    "AssertResult",
    "BaseElement",
    "ElementById",
    "ElementType",
    "ExecutionResult",
    "ExtractOption",
    "FileChooserHandler",
    "FileChooserRegistration",
    "InsightAction",
    "InterfaceType",
    "LocateOption",
    "LocateResult",
    "NodeType",
    "OnTaskStartTip",
    "Point",
    "Rect",
    "ScrollParam",
    "Size",
    "T",
    "TUserPrompt",
    "UIContext",
    "UINode",
    "UITree",
    "supports_interface_extension",
]
