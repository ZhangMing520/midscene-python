"""Jev (System One) adapter callbacks (upstream ai-model/models/jev/*)."""

from typing import Callable

def _jev_boolean_fn() -> Callable:
    from midscene.core.ai_model.models.jev.boolean import jev_boolean

    return jev_boolean


def _jev_locate_fn() -> Callable:
    from midscene.core.ai_model.models.jev.locate import jev_locate

    return jev_locate
