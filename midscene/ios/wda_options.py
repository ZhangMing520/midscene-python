"""WDA connection option validation (upstream wda-options.ts)."""

from typing import Any, Dict, Optional
from urllib.parse import urlparse


def normalize_mjpeg_stream_url(value: str) -> str:
    """Validate and normalize a WDA MJPEG stream URL (upstream)."""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("wdaMjpegUrl must be an absolute HTTP(S) URL.")
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username
        or parsed.password
        or "#" in value
    ):
        raise ValueError(
            "wdaMjpegUrl must use HTTP(S) without credentials or a fragment."
        )
    return value


def assert_wda_connection_options(
    options: Optional[Dict[str, Any]] = None,
) -> None:
    """Reject mutually exclusive WDA connection settings (upstream)."""
    options = options or {}
    if options.get("wdaBaseUrl") is not None and (
        options.get("wdaHost") is not None or options.get("wdaPort") is not None
    ):
        raise ValueError(
            "wdaBaseUrl cannot be used with wdaHost or wdaPort. "
            "Choose one WDA connection method."
        )
    if (
        options.get("wdaMjpegUrl") is not None
        and options.get("wdaMjpegPort") is not None
    ):
        raise ValueError(
            "wdaMjpegUrl cannot be used with wdaMjpegPort. "
            "Choose one MJPEG connection method."
        )
    if options.get("wdaMjpegUrl") is not None:
        normalize_mjpeg_stream_url(options["wdaMjpegUrl"])


__all__ = ["assert_wda_connection_options", "normalize_mjpeg_stream_url"]
