"""Document scheduling helpers (upstream engine/scheduler.ts)."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from midscene.core.test_runner.engine._abort import is_aborted
from midscene.core.test_runner.engine.execution_failure import WorkflowAggregateError


async def run_document_attempts(
    options: Mapping[str, Any],
    run: Callable[[int], Awaitable[Any]],
) -> None:
    """A rejected attempt is an infrastructure failure and is never replayed."""
    retry = int(options.get("retry", 0))
    signal = options.get("signal")
    should_stop = options.get("shouldStop") or (lambda: False)
    for attempt_index in range(retry + 1):
        if is_aborted(signal) or should_stop():
            return
        status = await run(attempt_index)
        if status != "failed":
            return


async def run_concurrent_jobs(
    items: Sequence[Any],
    options: Mapping[str, Any],
    run: Callable[[Any, int], Awaitable[None]],
) -> None:
    """Ordered admission, bounded concurrency, results in invocation order."""
    concurrency = max(0, int(options.get("concurrency", 1)))
    should_stop = options.get("shouldStop") or (lambda: False)
    cursor = [0]

    async def worker() -> None:
        while cursor[0] < len(items) and not should_stop():
            index = cursor[0]
            cursor[0] += 1
            await run(items[index], index)

    results = await asyncio.gather(
        *(worker() for _ in range(min(concurrency, len(items)))),
        return_exceptions=True,
    )
    errors: list[BaseException] = [
        result for result in results if isinstance(result, BaseException)
    ]
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise WorkflowAggregateError(errors, "Document scheduling failed")


__all__ = ["run_concurrent_jobs", "run_document_attempts"]
