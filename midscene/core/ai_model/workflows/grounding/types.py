"""Grounding workflow types (upstream workflows/grounding/types.ts)."""

from collections.abc import Awaitable
from typing import Any, Protocol, TypedDict


class SearchAreaImageMapping(TypedDict):
    offset: dict[str, float]
    scale: float


class SearchAreaImage(TypedDict):
    imageBase64: str
    width: int
    height: int


class SearchAreaConfig(TypedDict):
    source_rect: dict[str, float]
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
    parse_result: dict[str, Any]
    raw_response: Any
    raw_assistant_output: dict[str, Any] | None
    usage: dict[str, Any] | None
    reasoning_content: str | None


class LocateModelResponse(TypedDict, total=False):
    """Resolved locate-model output, before coordinate mapping."""

    locatedPixelResult: dict[str, Any]
    raw_response: str
    rawAssistantOutput: dict[str, Any] | None
    usage: dict[str, Any] | None
    reasoningContent: str | None
    errors: list[str]


class LocateFn(Protocol):
    def __call__(
        self,
        locate_request: LocateRequest | None = None,
        *,
        target_element_description: Any = None,
        locate_image: LocateImage | None = None,
        model_runtime: Any = None,
    ) -> Awaitable[LocateModelResponse]: ...


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
