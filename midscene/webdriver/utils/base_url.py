"""WebDriver server URL normalization."""


def normalize_webdriver_base_url(base_url: str) -> str:
    """Strip trailing slashes and add a scheme when omitted.

    Mirrors upstream `normalizeWebDriverBaseUrl` in behavior for full HTTP(S)
    URLs, while additionally accepting the `host:port` shorthand.
    """
    url = base_url.rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url
