"""Device option helpers (upstream device/device-options.ts)."""

from typing import Any


def _supported_kwargs(method: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keyword arguments the platform primitive does not accept."""
    import inspect

    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


def _scroll_supported_kwargs(device: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    return _supported_kwargs(device.scroll, kwargs)


def _accepts_keyword(fn: Any, name: str) -> bool:
    """True when fn can be called with the keyword name."""
    import inspect

    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
