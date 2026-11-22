"""Web agent init args (upstream web-integration/agent-init-args.ts).

The CLI accepts agent behavior overrides (AI contexts, replanning limits,
typing/action delays) plus a start URL.  These helpers normalize the loose
YAML/CLI mapping into the camelCase shape the rendering layer and the agent
options understand.
"""

import re
from typing import Any, Dict, List, Optional, TypedDict

from midscene.shared.agent_tools.agent_behavior_init_args import (
    AGENT_BEHAVIOR_INIT_ARG_SHAPE,
    extract_agent_behavior_init_args,
)
from midscene.shared.agent_tools.types import ToolSchema, schema_field

_HTTP_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_HTTP_HEADER_ERROR = 'Expected an HTTP header in "Name:Value" format.'


class WebAgentInitArgs(TypedDict, total=False):
    """Web-specific agent init args (upstream WebAgentInitArgs)."""

    url: str
    aiContexts: Dict[str, str]
    aiActContext: str
    aiActionContext: str
    replanningCycleLimit: int
    waitAfterAction: float
    screenshotShrinkFactor: float


class WebCdpAgentInitArgs(WebAgentInitArgs, total=False):
    """Web CDP init args, adding normalized HTTP headers."""

    extraHTTPHeaders: Dict[str, str]


WEB_AGENT_INIT_ARG_SHAPE: ToolSchema = {
    "url": schema_field(
        "string",
        "URL to open in new tab (omit to use current page)",
        optional=True,
    ),
    **AGENT_BEHAVIOR_INIT_ARG_SHAPE,
}

WEB_CDP_AGENT_INIT_ARG_SHAPE: ToolSchema = {
    **WEB_AGENT_INIT_ARG_SHAPE,
    "extraHttpHeader": schema_field(
        "string | string[]",
        'Extra HTTP header sent with page requests in CDP mode, in '
        '"Name:Value" format. Repeat --extra-http-header to send multiple '
        "headers.",
        optional=True,
    ),
}


def _parse_header_entry(entry: Any) -> Dict[str, str]:
    if not isinstance(entry, str):
        raise ValueError(_HTTP_HEADER_ERROR)
    separator_index = entry.find(":")
    if separator_index <= 0:
        raise ValueError(_HTTP_HEADER_ERROR)
    name = entry[:separator_index].strip()
    if not _HTTP_HEADER_NAME_PATTERN.match(name):
        raise ValueError(_HTTP_HEADER_ERROR)
    return {name: entry[separator_index + 1 :].strip()}


def _parse_http_headers(value: Any) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    entries: List[Any]
    if isinstance(value, str):
        entries = [value]
    elif isinstance(value, list):
        if not value:
            raise ValueError(_HTTP_HEADER_ERROR)
        entries = value
    else:
        raise ValueError(_HTTP_HEADER_ERROR)

    headers: Dict[str, str] = {}
    for entry in entries:
        headers.update(_parse_header_entry(entry))
    return headers


def adapt_web_agent_init_args(
    extracted: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Keep only the supported web/agent behavior init args."""
    if not extracted:
        return None

    init_args: Dict[str, Any] = {}
    if isinstance(extracted.get("url"), str):
        init_args["url"] = extracted["url"]
    behavior_args = extract_agent_behavior_init_args(extracted)
    if behavior_args:
        init_args.update(behavior_args)

    return init_args or None


def get_agent_init_args(
    extracted: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return normalized agent init args (alias of adapt_web_agent_init_args)."""
    return adapt_web_agent_init_args(extracted)


def adapt_web_cdp_agent_init_args(
    extracted: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Normalize CDP web init args, including ``extraHttpHeader`` entries."""
    if not extracted:
        return None

    base_args = adapt_web_agent_init_args(extracted)
    headers = _parse_http_headers(extracted.get("extraHttpHeader"))
    init_args: Dict[str, Any] = dict(base_args or {})
    if headers is not None:
        init_args["extraHTTPHeaders"] = headers

    return init_args or None


__all__ = [
    "WEB_AGENT_INIT_ARG_SHAPE",
    "WEB_CDP_AGENT_INIT_ARG_SHAPE",
    "WebAgentInitArgs",
    "WebCdpAgentInitArgs",
    "adapt_web_agent_init_args",
    "adapt_web_cdp_agent_init_args",
    "get_agent_init_args",
]
