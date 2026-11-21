"""Per-request timeout resolution (upstream service-caller/request-timeout.ts)."""

from typing import Optional

def resolve_effective_timeout_ms(timeout: Optional[float]) -> Optional[float]:
    """Per-request hard timeout in milliseconds. None disables the Midscene timeout."""
    if timeout is None:
        return 180_000.0
    if timeout <= 0:
        return None
    return float(timeout)
