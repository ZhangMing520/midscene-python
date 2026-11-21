"""Async execution context for YAML runs (upstream yaml/execution-context.*).

Upstream ships node/stub variants; Python always has contextvars, so a single
implementation covers both.
"""

import contextvars
from typing import Any

supports_async_context = True

_yaml_execution_context: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "midscene_yaml_execution_context", default=None
)


def create_execution_context() -> contextvars.ContextVar:
    return _yaml_execution_context
