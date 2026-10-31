"""
Midscene Python - AI-powered automation framework

A Python implementation of Midscene, providing AI-driven automation
capabilities for Web and Android platforms. The AI model layer is synced
with upstream web-infra-dev/midscene v1.17.4 (multi-slot model config,
standard planning/locate/insight protocols and prompts).
"""

from .core.agent import Agent
from .core.insight import Insight
from .core.types import (
    AgentOptions,
    AssertResult,
    ExecutionResult,
    ExtractOption,
    LocateOption,
    LocateResult,
    UIContext,
)

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
]
