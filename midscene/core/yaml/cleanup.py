"""Run registered cleanup callbacks (upstream yaml/cleanup.ts)."""

from typing import Any, Awaitable, Callable, List


async def run_free_fn_cleanup(free_fns: List[Callable[[], Awaitable[Any]]]) -> None:
    """Run every cleanup, then re-raise the first or an aggregate error."""
    errors: List[BaseException] = []
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
