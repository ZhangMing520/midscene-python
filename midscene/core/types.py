"""
Core types and interfaces for Midscene Python
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable, Generic, TypeVar
from pydantic import BaseModel

# Type variables
ElementType = TypeVar('ElementType', bound='BaseElement')
T = TypeVar('T')


class InterfaceType(str, Enum):
    """Interface type enumeration"""
    WEB = "web"
    ANDROID = "android"


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
        return Point(
            x=self.left + self.width / 2,
            y=self.top + self.height / 2
        )


class BaseElement(BaseModel):
    """Base UI element interface"""
    id: str
    content: str
    rect: Rect
    center: tuple[float, float]
    node_type: NodeType = NodeType.OTHER
    attributes: Dict[str, Any] = field(default_factory=dict)
    is_visible: bool = True
    xpaths: Optional[List[str]] = None
    
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
    attributes: Dict[str, Any] = field(default_factory=dict)
    is_visible: bool = True
    children: List['UINode'] = field(default_factory=list)


class UITree(BaseModel):
    """UI tree representation"""
    node: UINode
    children: List['UITree'] = field(default_factory=list)


class UIContext(BaseModel, Generic[ElementType]):
    """UI context containing screenshot and element information"""
    screenshot_base64: str
    size: Size
    content: List[ElementType]
    tree: UITree
    
    
class AIUsageInfo(BaseModel):
    """AI usage information"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: Optional[float] = None


class LocateResult(BaseModel):
    """Element locate result.

    After the upstream sync, locate is coordinate-based: `center` is the
    (x, y) click point and `rect` the element bounding box when available.
    `element` is kept for backward compatibility and stays None in the
    pure-vision flow.
    """
    element: Optional[BaseElement] = None
    rect: Optional[Rect] = None
    center: Optional[List[float]] = None
    description: Optional[str] = None
    raw_response: Optional[str] = None


class ExecutionResult(BaseModel, Generic[T]):
    """Generic execution result"""
    success: bool = True
    data: Optional[Any] = None
    error: Optional[str] = None
    usage: Optional[AIUsageInfo] = None


class AssertResult(BaseModel):
    """Assertion result"""
    passed: bool
    thought: str = ""
    message: str = ""


# Type aliases
TUserPrompt = Union[str, Dict[str, Any]]
ElementById = Callable[[str], Optional[BaseElement]]
OnTaskStartTip = Callable[[str], Union[None, Awaitable[None]]]


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

    @abstractmethod
    async def action_space(self) -> List[str]:
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
    async def scroll(self, direction: str, distance: Optional[int] = None, **kwargs) -> None:
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

    async def swipe(self, direction: str, distance: Optional[int] = None) -> None:
        raise NotImplementedError("swipe is not supported on this interface")

    async def drag_and_drop(self, from_point, to_point) -> None:
        raise NotImplementedError("drag_and_drop is not supported on this interface")

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        raise NotImplementedError("long_press is not supported on this interface")

    # Optional element locate-cache hooks -----------------------------------

    async def cache_feature_for_point(
        self, center: List[float], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build a serializable feature for the element at `center`.

        The feature is persisted in the locate cache and must be resolvable by
        `rect_matches_cache_feature` on a later run (upstream
        `interface.cacheFeatureForPoint`).
        """
        raise NotImplementedError(
            "cache_feature_for_point is not supported on this interface"
        )

    async def rect_matches_cache_feature(
        self, feature: Dict[str, Any]
    ) -> Optional[Rect]:
        """Resolve a cached feature back to a rect, or None when it is stale."""
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
class AgentOptions:
    """Agent configuration options"""
    test_id: Optional[str] = None
    cache_id: Optional[str] = None
    group_name: str = "Midscene Report"
    group_description: str = ""
    generate_report: bool = True
    auto_print_report_msg: bool = True
    ai_action_context: Optional[str] = None
    report_file_name: Optional[str] = None
    # Model configuration. Either an env-style dict (MIDSCENE_MODEL_NAME,
    # MIDSCENE_MODEL_API_KEY, MIDSCENE_MODEL_BASE_URL, MIDSCENE_MODEL_FAMILY,
    # MIDSCENE_PLANNING_MODEL_* ...), or a legacy callable returning such a dict.
    model_config: Optional[Union[Dict[str, str], Callable]] = None
    # Callback fired at the start of each execution task: (tip: str) -> None
    on_task_start_tip: Optional[Callable] = None
    # Override the replanning cycle limit (default: adapter value, 20 standard)
    replanning_cycle_limit: Optional[int] = None


@dataclass
class LocateOption:
    """Locate operation options"""
    prompt: Optional[TUserPrompt] = None
    deep_think: bool = False
    cacheable: bool = True
    xpath: Optional[str] = None
    ui_context: Optional[UIContext] = None


@dataclass
class ExtractOption:
    """Extract operation options"""
    dom_included: Union[bool, str] = False  # False, True, or 'visible-only'
    screenshot_included: bool = True
    return_thought: bool = False
    is_wait_for_assert: bool = False
    do_not_throw_error: bool = False


class ScrollParam(BaseModel):
    """Scroll parameters"""
    direction: str  # 'down', 'up', 'left', 'right'
    scroll_type: str  # 'once', 'untilBottom', 'untilTop', 'untilLeft', 'untilRight'
    distance: Optional[int] = None  # distance in pixels