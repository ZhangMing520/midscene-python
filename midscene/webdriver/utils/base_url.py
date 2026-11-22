"""WebDriver server URL normalization (upstream utils/base-url.ts)."""

from urllib.parse import urlsplit


def normalize_web_driver_base_url(base_url: str) -> str:
    """Normalize a WebDriver server URL before appending endpoint paths.

    Only full HTTP(S) URLs without credentials, query or fragment are
    accepted; trailing slashes are stripped.
    """
    try:
        parts = urlsplit(base_url)
    except ValueError as error:
        raise ValueError(
            "Invalid WebDriver base URL: expected a full HTTP(S) URL"
        ) from error

    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or "?" in base_url
        or "#" in base_url
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "WebDriver base URL must be an HTTP(S) URL without credentials, "
            "query, or fragment"
        )

    normalized = parts._replace(path=parts.path.rstrip("/"), query="", fragment="")
    if not normalized.path:
        # urlsplit keeps an empty path for "http://host"; urljoin-style output
        # must still include the scheme and host.
        return f"{normalized.scheme}://{normalized.netloc}"
    return (
        f"{normalized.scheme}://{normalized.netloc}{normalized.path}"
    )


def normalize_webdriver_base_url(base_url: str) -> str:
    """Backward-compatible alias for the pre-upstream Python name."""
    return normalize_web_driver_base_url(base_url)


__all__ = ["normalize_web_driver_base_url", "normalize_webdriver_base_url"]
