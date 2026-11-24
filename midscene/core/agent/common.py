"""Shared agent constants (upstream agent/common.ts)."""

import re

# Task types for model-fallback resolution (upstream ModelTaskType)
TASK_TYPE_PLANNING = "planning"

TASK_TYPE_LOCATE = "locate"

TASK_TYPE_EXTRACT = "extract"

TASK_TYPE_BOOLEAN = "boolean"

MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP = 5

DEFAULT_WAIT_AFTER_ACTION_MS = 300

# Transient browser errors worth retrying when building the UI context
# (upstream BROWSER_NAVIGATION_ERROR_PATTERN in web-integration).
BROWSER_NAVIGATION_ERROR_PATTERN = re.compile(
    "execution context was destroyed|frame was detached|target closed|"
    "page has been closed|context was destroyed|net::ERR_ABORTED",
    re.IGNORECASE,
)

CONTEXT_RETRY_MAX = 3

CONTEXT_RETRY_DELAY_MS = 1500

AGENT_AI_CONTEXT_KEYS = (
    "default",
    "aiAct",
    "aiTap",
    "aiRightClick",
    "aiMiddleClick",
    "aiDoubleClick",
    "aiHover",
    "aiInput",
    "aiKeyboardPress",
    "aiScroll",
    "aiLongPress",
    "aiClearInput",
    "aiLocate",
    "aiQuery",
    "aiBoolean",
    "aiNumber",
    "aiString",
    "aiAsk",
    "aiAssert",
    "aiWaitFor",
)
