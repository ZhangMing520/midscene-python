"""Insight protocol types (upstream model-adapter/insight-protocol.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict


class InsightDataOutputProtocol(TypedDict):
    tag_names: tuple[str, ...]
    rules: str
    placeholder: str
    build_example: Callable[[str], str]
    parse: Callable[[str], Any]


class InsightProtocol(TypedDict):
    response_prefix: str | None
    data_output: InsightDataOutputProtocol


__all__ = ["InsightDataOutputProtocol", "InsightProtocol"]
