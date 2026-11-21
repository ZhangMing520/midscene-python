"""Insight protocol types (upstream model-adapter/insight-protocol.ts)."""

from typing import Any, Callable, Optional, Tuple, TypedDict


class InsightDataOutputProtocol(TypedDict):
    tag_names: Tuple[str, ...]
    rules: str
    placeholder: str
    build_example: Callable[[str], str]
    parse: Callable[[str], Any]


class InsightProtocol(TypedDict):
    response_prefix: Optional[str]
    data_output: InsightDataOutputProtocol


__all__ = ["InsightDataOutputProtocol", "InsightProtocol"]
