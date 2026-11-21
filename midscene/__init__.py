"""
Midscene Python - AI-powered automation framework

A Python implementation of Midscene, providing AI-driven automation
capabilities for Web and Android platforms. The AI model layer is synced
with upstream web-infra-dev/midscene v1.18.2 (multi-slot model config,
standard planning/locate/insight protocols and prompts).
"""

from midscene.core.agent.agent import Agent
from midscene.core.element_describer import (
    describe_element_at_point,
    verify_element_description_at_point,
    verify_locator,
)
from midscene.core.agent.insight import Insight
from midscene.core.types import (
    AssertResult,
    ExecutionResult,
    ExtractOption,
    LocateOption,
    LocateResult,
    UIContext,
)
from midscene.core.agent.agent_options import AgentOptions

__version__ = "0.2.0"

__all__ = [
    "Agent",
    "Insight",
    "AgentOptions",
    "UIContext",
    "LocateResult",
    "LocateOption",
    "ExtractOption",
    "AssertResult",
    "ExecutionResult",
    "describe_element_at_point",
    "verify_element_description_at_point",
    "verify_locator",
]
