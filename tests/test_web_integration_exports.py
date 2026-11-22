"""Export parity checks for web-integration modules touched in Phase 4C.

The referenced upstream modules (bridge-mode/browser.ts, bridge-mode/common.ts,
playwright/page.ts, web-element.ts) expose only constants/types or thin
re-exports, so there is no dedicated upstream unit-test file to port.
"""

import math

import pytest


class TestBridgeModeCommon:
    def test_exposes_default_local_endpoint_and_page_type(self):
        from midscene.web_integration.bridge_mode.common import (
            BRIDGE_ERROR_CODE_NO_CLIENT_CONNECTED,
            BRIDGE_PAGE_TYPE,
            DefaultBridgeServerHost,
            DefaultBridgeServerPort,
            DefaultLocalEndpoint,
        )

        assert DefaultLocalEndpoint == "http://127.0.0.1:3766"
        assert (
            DefaultLocalEndpoint
            == f"http://{DefaultBridgeServerHost}:{DefaultBridgeServerPort}"
        )
        assert BRIDGE_PAGE_TYPE == "page-over-chrome-extension-bridge"
        assert (
            BRIDGE_ERROR_CODE_NO_CLIENT_CONNECTED == "no-client-connected"
        )

    def test_exposes_bridge_event_names_as_constants(self):
        from midscene.web_integration.bridge_mode.common import BridgeEvent

        assert BridgeEvent.Call.value == "bridge-call"
        assert BridgeEvent.CallResponse.value == "bridge-call-response"
        assert BridgeEvent.UpdateAgentStatus.value == "bridge-update-agent-status"
        assert BridgeEvent.Message.value == "bridge-message"
        assert BridgeEvent.Connected.value == "bridge-connected"
        assert BridgeEvent.Refused.value == "bridge-refused"
        assert BridgeEvent.ConnectNewTabWithUrl.value == "connectNewTabWithUrl"
        assert BridgeEvent.ConnectCurrentTab.value == "connectCurrentTab"
        assert BridgeEvent.GetBrowserTabList.value == "getBrowserTabList"
        assert BridgeEvent.SetDestroyOptions.value == "setDestroyOptions"
        assert BridgeEvent.SetActiveTabId.value == "setActiveTabId"
        assert (
            BridgeEvent.RegisterFileChooserAccept.value
            == "registerFileChooserAccept"
        )
        assert (
            BridgeEvent.ClearFileChooserAccept.value
            == "clearFileChooserAccept"
        )
        assert BridgeEvent.GetFileChooserError.value == "getFileChooserError"

    def test_exposes_mouse_and_keyboard_event_names(self):
        from midscene.web_integration.bridge_mode.common import (
            KeyboardEvent,
            MouseEvent,
        )

        assert MouseEvent.PREFIX.value == "mouse."
        assert MouseEvent.Click.value == "mouse.click"
        assert MouseEvent.Wheel.value == "mouse.wheel"
        assert MouseEvent.Move.value == "mouse.move"
        assert MouseEvent.Drag.value == "mouse.drag"

        assert KeyboardEvent.PREFIX.value == "keyboard."
        assert KeyboardEvent.Type.value == "keyboard.type"
        assert KeyboardEvent.InsertText.value == "keyboard.insertText"
        assert KeyboardEvent.Press.value == "keyboard.press"


class TestBridgePageBrowserSide:
    def test_browser_module_reexports_the_page_class(self):
        from midscene.web_integration.bridge_mode.browser import (
            ExtensionBridgePageBrowserSide,
        )
        from midscene.web_integration.bridge_mode.page_browser_side import (
            BridgeWebPage,
            ExtensionBridgePageBrowserSide as PageClass,
        )

        assert ExtensionBridgePageBrowserSide is PageClass
        assert BridgeWebPage is PageClass

    @pytest.mark.asyncio
    async def test_destroy_delegates_to_close(self):
        from midscene.web_integration.bridge_mode.page_browser_side import (
            ExtensionBridgePageBrowserSide,
        )

        page = ExtensionBridgePageBrowserSide()
        calls = []

        async def fake_close():
            calls.append("close")

        page.close = fake_close
        await page.destroy()

        assert calls == ["close"]


class TestWebElement:
    def test_web_element_info_impl_computes_the_floored_center(self):
        from midscene.core.types import NodeType, Rect
        from midscene.web_integration.web_element import WebElementInfoImpl

        rect = Rect(left=10, top=20, width=31, height=41)
        element = WebElementInfoImpl(
            content="Submit",
            rect=rect,
            id="el-1",
            attributes={"nodeType": NodeType.BUTTON, "id": "submit"},
            index_id=3,
            xpaths=["//button[@id='submit']"],
            is_visible=True,
        )

        assert element.center == (
            math.floor(rect.left + rect.width / 2),
            math.floor(rect.top + rect.height / 2),
        )
        assert element.id == "el-1"
        assert element.content == "Submit"
        assert element.rect == rect
        assert element.index_id == 3
        assert element.attributes == {"nodeType": NodeType.BUTTON, "id": "submit"}
        assert element.xpaths == ["//button[@id='submit']"]
        assert element.is_visible is True

    def test_limit_open_new_tab_script_matches_upstream_exactly(self):
        from midscene.web_integration.web_element import (
            LIMIT_OPEN_NEW_TAB_SCRIPT,
        )

        assert LIMIT_OPEN_NEW_TAB_SCRIPT == """
if (!window.__MIDSCENE_NEW_TAB_INTERCEPTOR_INITIALIZED__) {
  window.__MIDSCENE_NEW_TAB_INTERCEPTOR_INITIALIZED__ = true;

  // Intercept the window.open method (only once)
  window.open = function(url) {
    console.log('Blocked window.open:', url);
    window.location.href = url;
    return null;
  };

  // Block all a tag clicks with target="_blank" (only once)
  document.addEventListener('click', function(e) {
    const target = e.target.closest('a');
    if (target && target.target === '_blank') {
      e.preventDefault();
      console.log('Blocked new tab:', target.href);
      window.location.href = target.href;
      target.removeAttribute('target');
    }
  }, true);
}
"""


def test_playwright_web_page_module_exposes_web_page_class():
    from midscene.web_integration.playwright.page import (
        PlaywrightWebPage,
        WebPage,
    )

    assert WebPage is PlaywrightWebPage
