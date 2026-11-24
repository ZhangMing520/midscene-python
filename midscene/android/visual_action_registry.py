"""Visual action registry (upstream android/src/visual-action-registry.ts).

Registers actions at one boundary so every caller observes the same
post-action frame freshness behavior.
"""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any


def create_visual_action_registry(
    definitions: dict[str, Callable[..., Any]],
    on_action_settled: Callable[[str], Awaitable[Any]],
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Wrap each action so `on_action_settled` runs after it settles."""
    registered: dict[str, Callable[..., Awaitable[Any]]] = {}

    for action_name, dispatch in definitions.items():

        async def wrapper(
            *args: Any,
            _dispatch: Callable[..., Any] = dispatch,
            _name: str = action_name,
            **kwargs: Any,
        ) -> Any:
            try:
                result = _dispatch(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            finally:
                settled = on_action_settled(_name)
                if inspect.isawaitable(settled):
                    await settled

        registered[action_name] = wrapper

    return registered


__all__ = ["create_visual_action_registry"]
