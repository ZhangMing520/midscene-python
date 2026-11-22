"""Port of upstream packages/cli/tests/unit-test/cli-utils.test.ts.

Only the dot-notation target-option cases are ported. Python's parser
(``_parse_cli_target_overrides``) normalizes every dotted key to camelCase and
ignores unknown target sections, so the assertions keep the upstream values
while matching that single output format.
"""

import asyncio

from midscene.cli.args import (
    _parse_cli_target_overrides,
    find_only_item_in_args,
    order_matters_parse,
)
from midscene.cli.cli_utils import parse_process_args


def test_should_parse_nested_web_and_android_options_in_camel_case():
    options = _parse_cli_target_overrides(
        [
            "--web.userAgent",
            "test-ua",
            "--web.viewportWidth",
            "1024",
            "--web.viewportHeight",
            "768",
            "--android.deviceId",
            "test-device",
        ]
    )

    assert options["web"] == {
        "userAgent": "test-ua",
        "viewportWidth": 1024,
        "viewportHeight": 768,
    }
    assert options["android"] == {"deviceId": "test-device"}


def test_should_parse_nested_web_and_android_options_in_kebab_case():
    options = _parse_cli_target_overrides(
        [
            "--web.user-agent",
            "test-ua-kebab",
            "--web.viewport-width",
            "1280",
            "--web.viewport-height",
            "1024",
            "--android.device-id",
            "test-device-kebab",
        ]
    )

    assert options["web"] == {
        "userAgent": "test-ua-kebab",
        "viewportWidth": 1280,
        "viewportHeight": 1024,
    }
    assert options["android"] == {"deviceId": "test-device-kebab"}


def test_parse_process_args_keeps_nested_values_and_both_formats(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "midscene",
            "path/to/script.yml",
            "--headed",
            "--keep-window",
            "--share-browser-context",
            "--reuse-page",
            "--continue-on-error",
            "--concurrent",
            "3",
            "--retry",
            "5",
            "--summary",
            "summary.html",
            "--web.user-agent",
            "test-ua",
            "--web.viewport-width",
            "1024",
            "--web.viewport-height",
            "768",
            "--android.device-id",
            "test-device",
            "--harmony.auto-dismiss-keyboard",
            "true",
            "--ios.auto-dismiss-keyboard",
            "true",
            "--setup",
            "setup.yml",
            "--dotenv-override",
            "--dotenv-debug",
        ],
    )

    parsed = asyncio.run(parse_process_args())

    assert parsed["path"] == "path/to/script.yml"
    assert parsed["files"] is None
    options = parsed["options"]
    assert options["_"] == ["path/to/script.yml"]
    assert options["headed"] is True
    assert options["keep-window"] is True
    assert options["share-browser-context"] is True
    assert options["reuse-page"] is True
    assert options["continue-on-error"] is True
    assert options["concurrent"] == 3
    assert options["retry"] == 5
    assert options["summary"] == "summary.html"
    assert options["setup"] == "setup.yml"
    assert options["dotenv-override"] is True
    assert options["dotenv-debug"] is True
    assert options["web"]["userAgent"] == "test-ua"
    assert options["web"]["user-agent"] == "test-ua"
    assert options["web"]["viewportWidth"] == 1024
    assert options["web"]["viewport-width"] == 1024
    assert options["web"]["viewportHeight"] == 768
    assert options["web"]["viewport-height"] == 768
    assert options["android"]["deviceId"] == "test-device"
    assert options["android"]["device-id"] == "test-device"
    assert options["harmony"]["autoDismissKeyboard"] == "true"
    assert options["harmony"]["auto-dismiss-keyboard"] == "true"
    assert options["ios"]["autoDismissKeyboard"] == "true"
    assert options["ios"]["auto-dismiss-keyboard"] == "true"


def test_parse_process_args_supports_files_and_no_booleans(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "midscene",
            "--files",
            "a.yml",
            "b.yml",
            "--no-share-browser-context",
        ],
    )

    parsed = asyncio.run(parse_process_args())

    assert parsed["path"] is None
    assert parsed["files"] == ["a.yml", "b.yml"]
    assert parsed["options"]["share-browser-context"] is False


def test_find_only_item_in_args_matches_upstream_contract():
    assert find_only_item_in_args({"port": 3000}, "port") == 3000
    assert find_only_item_in_args({}, "port") is False
    assert find_only_item_in_args({"port": [3000]}, "port") == 3000
    try:
        find_only_item_in_args({"port": [3000, 4000]}, "port")
    except ValueError as error:
        assert "Multiple values found for port" in str(error)
    else:
        raise AssertionError("expected a ValueError")


def test_order_matters_parse_preserves_order_and_coerces_integers():
    assert order_matters_parse(
        ["--port", "3000", "--headed", "--host", "localhost"]
    ) == [
        {"name": "port", "value": 3000},
        {"name": "headed", "value": True},
        {"name": "host", "value": "localhost"},
    ]
