"""Standard locate protocol types and protocol helpers.

Synced from upstream packages/core/src/ai-model/model-adapter/locate-protocol.ts.
"""

from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict, Union


class ParsedLocatedLocateResponse(TypedDict, total=False):
    kind: Literal["located"]
    target: Any
    references: List[Any]
    error: str


class ParsedNotFoundLocateResponse(TypedDict, total=False):
    kind: Literal["not-found"]
    error: str


ParsedLocateResponse = Union[
    ParsedLocatedLocateResponse, ParsedNotFoundLocateResponse
]


class StandardLocateProtocol(TypedDict):
    system_prompt_introduction: str
    build_response_instructions: Callable[[Dict[str, Any]], str]
    build_user_prompt: Callable[[str], str]
    expected_json_object_response: bool
    parse_raw_response: Callable[[str, Dict[str, Any]], ParsedLocateResponse]


class StandardLocateProtocolContext(TypedDict, total=False):
    json_parser: Optional[Callable[..., Any]]


StandardLocateProtocolFactory = Callable[
    [StandardLocateProtocolContext], StandardLocateProtocol
]

StandardLocateProtocolDefinition = Union[
    StandardLocateProtocol, StandardLocateProtocolFactory
]


__all__ = [
    "ParsedLocatedLocateResponse",
    "ParsedLocateResponse",
    "ParsedNotFoundLocateResponse",
    "StandardLocateProtocol",
    "StandardLocateProtocolContext",
    "StandardLocateProtocolDefinition",
    "StandardLocateProtocolFactory",
]
