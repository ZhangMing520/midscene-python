"""Standard locate protocol types and protocol helpers.

Synced from upstream packages/core/src/ai-model/model-adapter/locate-protocol.ts.
"""

from collections.abc import Callable
from typing import Any, Literal, TypedDict


class ParsedLocatedLocateResponse(TypedDict, total=False):
    kind: Literal["located"]
    target: Any
    references: list[Any]
    error: str


class ParsedNotFoundLocateResponse(TypedDict, total=False):
    kind: Literal["not-found"]
    error: str


ParsedLocateResponse = ParsedLocatedLocateResponse | ParsedNotFoundLocateResponse


class StandardLocateProtocol(TypedDict):
    system_prompt_introduction: str
    build_response_instructions: Callable[[dict[str, Any]], str]
    build_user_prompt: Callable[[str], str]
    expected_json_object_response: bool
    parse_raw_response: Callable[[str, dict[str, Any]], ParsedLocateResponse]


class StandardLocateProtocolContext(TypedDict, total=False):
    json_parser: Callable[..., Any] | None


StandardLocateProtocolFactory = Callable[
    [StandardLocateProtocolContext], StandardLocateProtocol
]

StandardLocateProtocolDefinition = (
    StandardLocateProtocol | StandardLocateProtocolFactory
)


__all__ = [
    "ParsedLocatedLocateResponse",
    "ParsedLocateResponse",
    "ParsedNotFoundLocateResponse",
    "StandardLocateProtocol",
    "StandardLocateProtocolContext",
    "StandardLocateProtocolDefinition",
    "StandardLocateProtocolFactory",
]
