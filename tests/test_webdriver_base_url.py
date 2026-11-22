"""Synced from upstream ``packages/webdriver/tests/unit-test/base-url.test.ts``
(``normalizeWebDriverBaseUrl``)."""

import pytest


def test_normalizes_webdriver_base_url():
    from midscene.webdriver import normalize_web_driver_base_url

    assert (
        normalize_web_driver_base_url("https://gateway.example:8100/code/wda/")
        == "https://gateway.example:8100/code/wda"
    )
    assert (
        normalize_web_driver_base_url("https://gateway.example:8100/wda/code")
        == "https://gateway.example:8100/wda/code"
    )
    assert (
        normalize_web_driver_base_url("http://x:8100/") == "http://x:8100"
    )


def test_keeps_different_gateway_prefixes_separate():
    from midscene.webdriver import normalize_webdriver_base_url

    assert (
        normalize_webdriver_base_url(
            "https://gateway.example:8100/code/wda/"
        )
        == "https://gateway.example:8100/code/wda"
    )
    assert (
        normalize_webdriver_base_url("https://gateway.example:8100/wda/code")
        == "https://gateway.example:8100/wda/code"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://gateway.example/wda",
        "https://gateway.example/wda?token=abc",
        "https://gateway.example/wda?",
        "https://gateway.example/wda#",
        "https://user:pass@gateway.example/wda",
        "not a URL",
        "x:8100",
    ],
)
def test_rejects_unsupported_base_url(value):
    from midscene.webdriver import normalize_web_driver_base_url

    with pytest.raises(ValueError):
        normalize_web_driver_base_url(value)
