"""Constants shared by the bridge server and page (upstream bridge-mode/common.ts)."""

from typing import Optional

DefaultBridgeServerHost = "127.0.0.1"
DefaultBridgeServerPort = 3766
BridgeCallTimeout = 30000

BRIDGE_EVENT_CALL = "bridge-call"
BRIDGE_EVENT_CALL_RESPONSE = "bridge-call-response"
BRIDGE_EVENT_CONNECTED = "bridge-connected"
BRIDGE_EVENT_REFUSED = "bridge-refused"
BRIDGE_EVENT_UPDATE_AGENT_STATUS = "bridge-update-agent-status"
BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL = "connectNewTabWithUrl"
BRIDGE_EVENT_CONNECT_CURRENT_TAB = "connectCurrentTab"
BRIDGE_EVENT_GET_BROWSER_TAB_LIST = "getBrowserTabList"
BRIDGE_EVENT_SET_DESTROY_OPTIONS = "setDestroyOptions"
BRIDGE_EVENT_SET_ACTIVE_TAB_ID = "setActiveTabId"
BRIDGE_SIGNAL_KILL = "MIDSCENE_BRIDGE_SIGNAL_KILL"


def get_bridge_server_host(
    host: Optional[str] = None, allow_remote_access: bool = False
) -> str:
    """Resolve the listen host: explicit host > remote access > default."""
    if host:
        return host
    if allow_remote_access:
        return "0.0.0.0"
    return DefaultBridgeServerHost
