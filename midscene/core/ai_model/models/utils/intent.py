"""Locate intent helpers (upstream models/utils/intent.ts)."""

from typing import Optional


def is_locate_intent(intent: Optional[str]) -> bool:
    return intent == "locate"


__all__ = ["is_locate_intent"]
