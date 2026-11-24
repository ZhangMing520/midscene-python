"""Run registered cleanup callbacks (upstream yaml/cleanup.ts)."""

from collections.abc import Awaitable, Callable
from typing import Any


async def run_free_fn_cleanup(free_fns: list[Callable[[], Awaitable[Any]]]) -> None:
    """Run every cleanup, then re-raise the first or an aggregate error."""
    errors: list[BaseException] = []
    for cleanup in free_fns:
        try:
            await cleanup()
        except Exception as error:  # noqa: BLE001 - collected below
            errors.append(error)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise RuntimeError(
            "Multiple resource cleanup operations failed: "
            + "; ".join(str(error) for error in errors)
        )
