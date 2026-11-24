"""Constants shared by the bridge server and page (upstream bridge-mode/common.ts)."""

from enum import Enum

DefaultBridgeServerHost = "127.0.0.1"
DefaultBridgeServerPort = 3766
DefaultLocalEndpoint = f"http://{DefaultBridgeServerHost}:{DefaultBridgeServerPort}"
BridgeCallTimeout = 30000

DEFAULT_LOCAL_ENDPOINT = DefaultLocalEndpoint


class BridgeEvent(str, Enum):
    """Bridge socket event names (upstream enum BridgeEvent)."""

    Call = "bridge-call"
    CallResponse = "bridge-call-response"
    UpdateAgentStatus = "bridge-update-agent-status"
    Message = "bridge-message"
    Connected = "bridge-connected"
    Refused = "bridge-refused"
    ConnectNewTabWithUrl = "connectNewTabWithUrl"
    ConnectCurrentTab = "connectCurrentTab"
    GetBrowserTabList = "getBrowserTabList"
    SetDestroyOptions = "setDestroyOptions"
    SetActiveTabId = "setActiveTabId"
    RegisterFileChooserAccept = "registerFileChooserAccept"
    ClearFileChooserAccept = "clearFileChooserAccept"
    GetFileChooserError = "getFileChooserError"


class MouseEvent(str, Enum):
    """Mouse event names (upstream enum MouseEvent)."""

    PREFIX = "mouse."
    Click = "mouse.click"
    Wheel = "mouse.wheel"
    Move = "mouse.move"
    Drag = "mouse.drag"


class KeyboardEvent(str, Enum):
    """Keyboard event names (upstream enum KeyboardEvent)."""

    PREFIX = "keyboard."
    Type = "keyboard.type"
    InsertText = "keyboard.insertText"
    Press = "keyboard.press"


BRIDGE_PAGE_TYPE = "page-over-chrome-extension-bridge"
BRIDGE_ERROR_CODE_NO_CLIENT_CONNECTED = "no-client-connected"
BRIDGE_SIGNAL_KILL = "MIDSCENE_BRIDGE_SIGNAL_KILL"

BRIDGE_EVENT_CALL = BridgeEvent.Call.value
BRIDGE_EVENT_CALL_RESPONSE = BridgeEvent.CallResponse.value
BRIDGE_EVENT_CONNECTED = BridgeEvent.Connected.value
BRIDGE_EVENT_REFUSED = BridgeEvent.Refused.value
BRIDGE_EVENT_UPDATE_AGENT_STATUS = BridgeEvent.UpdateAgentStatus.value
BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL = BridgeEvent.ConnectNewTabWithUrl.value
BRIDGE_EVENT_CONNECT_CURRENT_TAB = BridgeEvent.ConnectCurrentTab.value
BRIDGE_EVENT_GET_BROWSER_TAB_LIST = BridgeEvent.GetBrowserTabList.value
BRIDGE_EVENT_SET_DESTROY_OPTIONS = BridgeEvent.SetDestroyOptions.value
BRIDGE_EVENT_SET_ACTIVE_TAB_ID = BridgeEvent.SetActiveTabId.value


def get_bridge_server_host(
    host: str | None = None, allow_remote_access: bool = False
) -> str:
    """Resolve the listen host: explicit host > remote access > default."""
    if host:
        return host
    if allow_remote_access:
        return "0.0.0.0"
    return DefaultBridgeServerHost


__all__ = [
    "BRIDGE_ERROR_CODE_NO_CLIENT_CONNECTED",
    "BRIDGE_EVENT_CALL",
    "BRIDGE_EVENT_CALL_RESPONSE",
    "BRIDGE_EVENT_CONNECTED",
    "BRIDGE_EVENT_CONNECT_CURRENT_TAB",
    "BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL",
    "BRIDGE_EVENT_GET_BROWSER_TAB_LIST",
    "BRIDGE_EVENT_REFUSED",
    "BRIDGE_EVENT_SET_ACTIVE_TAB_ID",
    "BRIDGE_EVENT_SET_DESTROY_OPTIONS",
    "BRIDGE_EVENT_UPDATE_AGENT_STATUS",
    "BRIDGE_PAGE_TYPE",
    "BRIDGE_SIGNAL_KILL",
    "BridgeCallTimeout",
    "BridgeEvent",
    "DefaultBridgeServerHost",
    "DefaultBridgeServerPort",
    "DefaultLocalEndpoint",
    "DEFAULT_LOCAL_ENDPOINT",
    "KeyboardEvent",
    "MouseEvent",
    "get_bridge_server_host",
]
