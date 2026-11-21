"""Observation window helper (upstream agent/observe-node.ts)."""

from typing import Any, Dict, Optional


def start_observing(agent, opt: Optional[Dict[str, Any]] = None):
    """Record a time window of UI frames (upstream startObserving).

    Options: `intervalMs` (default 1000, min 200), `maxFrames` (default 30,
    buffer is thinned past the cap while recording continues) and
    `watchdogMs` (default 5 minutes, 0 disables). `stop()` freezes the
    window into a UIObservation whose insight calls read the frames.

    TODO: docs/quickstart.md covers the YAML flow items but not this Python
    API yet.
    """
    from midscene.core.agent.ui_observer import UIObserver

    if agent._frozen:
        raise RuntimeError(
            "startObserving() cannot be used while the UI context is "
            "frozen (call unfreeze_page_context() first)"
        )
    return UIObserver(agent, opt)
