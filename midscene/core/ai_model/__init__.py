"""AI model layer synced from upstream web-infra-dev/midscene v1.17.4.

Architecture (packages/core/src/ai-model + packages/shared/src/env):
- env_config: per-intent model config (default/locate/insight/planning slots)
- adapters: per-model-family chat-completion params + locate result formats
- caller: OpenAI-compatible chat completion with retry/timeout/usage
- protocols: default planning (XML), locate (JSON), insight (data-json)
- prompts: planning/locate/insight/describe prompt builders
- workflows: grounding (aiLocateElement), insight (aiExtractElementInfo),
  planning (standardPlan)
"""

# New layered API
from .env_config import (
    ModelConfigManager,
    get_global_model_config_manager,
    get_preferred_language,
    override_ai_config,
)
from .adapters import ModelRuntime, get_model_adapter, get_model_runtime
from .caller import AIResponseParseError, call_generative_ai
from .locate_result import LocateResultCodec, create_locate_result_codec
from .protocols import (
    create_default_element_protocol,
    create_default_insight_protocol,
    create_default_planning_protocol,
)
from .workflows import (
    ConversationHistory,
    ai_extract_element_info,
    ai_locate_element,
    standard_plan,
)

# Connectivity test (upstream run-connectivity-test)
from .connectivity import run_connectivity_test
from .system_one import call_system_one, SystemOneError
from .siwc import (
    SiwcError,
    SiwcTokenExpiredError,
    siwc_token_manager,
    prepare_siwc_call,
)

# Legacy facade (kept so existing user code keeps working)
from .service import AIModelConfig, AIModelService


def get_model_runtime_config(intent: str = "default") -> dict:
    """Resolve the env-derived model config for one intent slot."""
    return get_global_model_config_manager().get_model_config(intent)


__all__ = [
    # config
    "ModelConfigManager",
    "get_global_model_config_manager",
    "get_model_runtime_config",
    "get_preferred_language",
    "override_ai_config",
    # runtime
    "ModelRuntime",
    "get_model_adapter",
    "get_model_runtime",
    # caller
    "AIResponseParseError",
    "call_generative_ai",
    # locate
    "LocateResultCodec",
    "create_locate_result_codec",
    # protocols
    "create_default_element_protocol",
    "create_default_insight_protocol",
    "create_default_planning_protocol",
    # workflows
    "ai_locate_element",
    "ai_extract_element_info",
    "standard_plan",
    "ConversationHistory",
    # connectivity & system-one & siwc
    "run_connectivity_test",
    "call_system_one",
    "SystemOneError",
    "SiwcError",
    "SiwcTokenExpiredError",
    "siwc_token_manager",
    "prepare_siwc_call",
    # legacy facade
    "AIModelConfig",
    "AIModelService",
]
