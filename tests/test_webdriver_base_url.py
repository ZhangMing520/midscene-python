"""Synced from upstream ``packages/webdriver/tests/unit-test/base-url.test.ts``
(``normalizeWebDriverBaseUrl``)."""


def test_normalizes_webdriver_base_url():
    from midscene.webdriver import normalize_webdriver_base_url

    assert normalize_webdriver_base_url("http://x:8100/") == "http://x:8100"
    assert normalize_webdriver_base_url("x:8100") == "http://x:8100"
