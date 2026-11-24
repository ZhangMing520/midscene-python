"""Boolean insight workflow (upstream workflows/insight/boolean.ts).

Boolean insights can be served by an adapter fast path (``insight_boolean_fn``)
instead of the generic ``data-json`` extraction workflow.
"""

import json
from collections.abc import Callable
from typing import Any

from midscene.core.ai_model.models.registry import ModelRuntime

BooleanFn = Callable[..., Any]


def resolve_boolean_fn(model_runtime: ModelRuntime) -> BooleanFn | None:
    """Return the adapter boolean fast path, if the model provides one."""
    return getattr(model_runtime.adapter, "insight_boolean_fn", None)


def _boolean_statement(demand: Any) -> str:
    if isinstance(demand, str):
        return demand
    return json.dumps(demand, ensure_ascii=False)


async def extract_boolean(
    boolean_fn: BooleanFn,
    data_query: str | dict[str, Any],
    context: Any,
    model_runtime: ModelRuntime,
    page_description: str = "",
    context_text: str | None = None,
) -> dict[str, Any]:
    """Run the adapter boolean fast path and wrap it as an insight result."""
    keys = list(data_query.keys()) if isinstance(data_query, dict) else []
    if len(keys) != 1:
        raise ValueError("Boolean insight tasks require exactly one result field.")

    statement = _boolean_statement(data_query[keys[0]])
    result = await boolean_fn(
        statement,
        context,
        model_runtime,
        page_description=page_description or "",
        context_text=context_text,
    )
    return {
        "parse_result": {"data": {keys[0]: bool(result.get("value"))}},
        "raw_response": result.get("raw_response", ""),
        "usage": result.get("usage"),
        "reasoning_content": None,
    }


__all__ = ["BooleanFn", "extract_boolean", "resolve_boolean_fn"]
