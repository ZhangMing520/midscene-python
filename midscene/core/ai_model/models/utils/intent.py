"""Locate intent helpers (upstream models/utils/intent.ts)."""


def is_locate_intent(intent: str | None) -> bool:
    return intent == "locate"


__all__ = ["is_locate_intent"]
