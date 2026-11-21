"""iOS WebDriver client alias (upstream ios/src/ios-webdriver-client.ts)."""

from midscene.ios.wda import WebDriverAgentBackend

IOSWebDriverClient = WebDriverAgentBackend

__all__ = ["IOSWebDriverClient"]
