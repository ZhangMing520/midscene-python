"""Deprecated debug env handling (upstream packages/shared/src/env/init-debug.ts)."""

import logging

from midscene.shared.env.basic import get_basic_env_value
from midscene.shared.env.constants import (
    MIDSCENE_DEBUG_MODEL_PROFILE,
    MIDSCENE_DEBUG_MODEL_RESPONSE,
)
from midscene.shared.logger import enable_debug

_logger = logging.getLogger(__name__)


def init_debug_config() -> None:
    """Translate deprecated debug env vars into debug namespaces."""
    should_print_timing = get_basic_env_value(MIDSCENE_DEBUG_MODEL_PROFILE)
    debug_config = ""
    if should_print_timing:
        _logger.warning(
            "MIDSCENE_DEBUG_MODEL_PROFILE is deprecated, "
            "use DEBUG=midscene:ai:profile instead"
        )
        debug_config = "ai:profile"

    should_print_model_response = get_basic_env_value(
        MIDSCENE_DEBUG_MODEL_RESPONSE
    )
    if should_print_model_response:
        _logger.warning(
            "MIDSCENE_DEBUG_MODEL_RESPONSE is deprecated, "
            "use DEBUG=midscene:ai:response instead"
        )
        debug_config = "ai:*" if debug_config else "ai:call"

    if debug_config:
        enable_debug(debug_config)


__all__ = ["init_debug_config"]
