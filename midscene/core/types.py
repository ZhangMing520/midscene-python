"""Backward-compatible re-export of the shared type vocabulary.

The definitions now live in :mod:`midscene.shared.types` (upstream
``packages/shared/src/types/index.ts``). This module keeps the historical
``midscene.core.types`` import path working without owning any definitions.
"""

from midscene.shared.types import (
    AbortError,
    AbortSignal,
    AbstractInterface,
    AIUsageInfo,
    AssertResult,
    BaseElement,
    ElementById,
    ElementType,
    ExecutionResult,
    ExtractOption,
    FileChooserHandler,
    FileChooserRegistration,
    InsightAction,
    InterfaceType,
    LocateOption,
    LocateResult,
    NodeType,
    OnTaskStartTip,
    Point,
    Rect,
    ScrollParam,
    Size,
    T,
    TUserPrompt,
    UIContext,
    UINode,
    UITree,
    supports_interface_extension,
)

# The generic agent progress bus uses this scope for aiAct events.
AI_ACT_PROGRESS_SCOPE = "aiAct"

__all__ = [
    "AI_ACT_PROGRESS_SCOPE",
    "AbortError",
    "AbortSignal",
    "AbstractInterface",
    "AIUsageInfo",
    "AssertResult",
    "BaseElement",
    "ElementById",
    "ElementType",
    "ExecutionResult",
    "ExtractOption",
    "FileChooserHandler",
    "FileChooserRegistration",
    "InsightAction",
    "InterfaceType",
    "LocateOption",
    "LocateResult",
    "NodeType",
    "OnTaskStartTip",
    "Point",
    "Rect",
    "ScrollParam",
    "Size",
    "T",
    "TUserPrompt",
    "UIContext",
    "UINode",
    "UITree",
    "supports_interface_extension",
]
