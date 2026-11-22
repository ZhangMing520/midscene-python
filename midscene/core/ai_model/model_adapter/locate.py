"""Locate adapter resolution (upstream model-adapter/locate.ts)."""

from typing import Any, Callable, Dict, TypedDict

from midscene.core.ai_model.model_adapter.default_locate_protocol import (
    create_default_element_protocol,
    create_default_search_area_protocol,
)
from midscene.core.ai_model.model_adapter.locate_protocol import (
    StandardLocateProtocol,
)
from midscene.core.ai_model.shared.model_locate_result.factory import (
    LocateResultCodec,
)


class LocateElementAdapter(TypedDict):
    protocol: StandardLocateProtocol
    result_codec: LocateResultCodec


class LocateAdapter(TypedDict, total=False):
    kind: str
    locate_fn: Callable[..., Any]
    prompt_order: Dict[str, Any]
    element: LocateElementAdapter
    search_area: LocateElementAdapter


def resolve_locate(adapter: Any) -> LocateAdapter:
    """Resolve the custom or standard locate adapter for a model adapter."""
    if adapter.locate_kind == "custom":
        locate_fn = adapter.locate_fn
        if locate_fn is None:
            raise ValueError(
                f"Custom locate adapter {adapter.family} has no locate_fn bound"
            )
        return {"kind": "custom", "locate_fn": locate_fn}

    element_protocol = adapter._element_protocol or create_default_element_protocol(
        adapter.json_parser
    )
    search_area_protocol = (
        adapter._search_area_protocol
        or create_default_search_area_protocol(adapter.json_parser)
    )
    return {
        "kind": "standard",
        "prompt_order": adapter.locate_prompt_order,
        "element": {
            "protocol": element_protocol,
            "result_codec": adapter.locate_result_codec,
        },
        "search_area": {
            "protocol": search_area_protocol,
            "result_codec": adapter.search_area_result_codec,
        },
    }


__all__ = ["LocateAdapter", "LocateElementAdapter", "resolve_locate"]
