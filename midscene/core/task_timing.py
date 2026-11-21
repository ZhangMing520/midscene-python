"""Set execution-task timing fields once (upstream core/src/task-timing.ts)."""

import time
from typing import Any, Dict, Optional
from loguru import logger


def set_timing_field_once(timing: Optional[Dict[str, Any]], field: str) -> None:
    """Record now() into a timing field only when it is still unset."""
    if not timing:
        logger.debug(f"[task-timing] timing object missing, skip set. field={field}")
        return
    value = int(time.time() * 1000)
    existing = timing.get(field)
    if existing is not None:
        logger.debug(
            f"[task-timing] duplicate timing field set ignored. "
            f"field={field}, existing={existing}, incoming={value}"
        )
        return
    timing[field] = value
