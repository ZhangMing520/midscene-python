"""Grounding workflow types (upstream workflows/grounding/types.ts)."""

from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict


class SearchAreaImageMapping(TypedDict):
    offset: Dict[str, float]
    scale: float


class SearchAreaImage(TypedDict):
    imageBase64: str
    width: int
    height: int


class SearchAreaConfig(TypedDict):
    source_rect: Dict[str, float]
    image: SearchAreaImage
    mapping: SearchAreaImageMapping


class LocateImage(TypedDict):
    imageBase64: str
    width: int
    height: int


class LocateOptions(TypedDict, total=False):
    ui_context: Any
    search_config: SearchAreaConfig
    model_runtime: Any
    abort_signal: Any


class LocateRequest(TypedDict):
    target_element_description: Any
    locate_image: LocateImage
    options: LocateOptions


class LocateResult(TypedDict, total=False):
    parse_result: Dict[str, Any]
    raw_response: Any
    raw_assistant_output: Optional[Dict[str, Any]]
    usage: Optional[Dict[str, Any]]
    reasoning_content: Optional[str]


class LocateModelResponse(TypedDict, total=False):
    """Resolved locate-model output, before coordinate mapping."""

    locatedPixelResult: Dict[str, Any]
    raw_response: str
    rawAssistantOutput: Optional[Dict[str, Any]]
    usage: Optional[Dict[str, Any]]
    reasoningContent: Optional[str]
    errors: List[str]


LocateFn = Callable[[LocateRequest], Awaitable[LocateModelResponse]]


__all__ = [
    "LocateFn",
    "LocateImage",
    "LocateModelResponse",
    "LocateOptions",
    "LocateRequest",
    "LocateResult",
    "SearchAreaConfig",
    "SearchAreaImage",
    "SearchAreaImageMapping",
]
