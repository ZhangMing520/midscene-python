"""System One (TypeSafe / Jev) protocol client.

Synced from upstream packages/core/src/ai-model/service-caller/system-one/*
and models/jev/*.
"""

import httpx
from loguru import logger

from midscene.core.ai_model.service_caller.system_one.call_system_one import (
    call_system_one,
    resolve_effective_timeout,
)
from midscene.core.ai_model.service_caller.system_one.prepare_system_one import (
    prepare_system_one,
)
from midscene.core.ai_model.service_caller.system_one.resolve_endpoint import (
    resolve_system_one_endpoint,
)
from midscene.core.ai_model.service_caller.system_one.schema import (
    SystemOneError,
    validate_system_one_response,
)
from midscene.core.ai_model.service_caller.system_one.utils import (
    encode_system_one_images,
)

__all__ = [
    "SystemOneError",
    "call_system_one",
    "encode_system_one_images",
    "logger",
    "prepare_system_one",
    "resolve_effective_timeout",
    "resolve_system_one_endpoint",
    "validate_system_one_response",
]
