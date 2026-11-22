"""Port of upstream packages/cli/tests/unit-test/cli-utils.test.ts.

Only the dot-notation target-option cases are ported. Python's parser
(``_parse_cli_target_overrides``) normalizes every dotted key to camelCase and
ignores unknown target sections, so the assertions keep the upstream values
while matching that single output format.
"""

from midscene.cli.args import _parse_cli_target_overrides


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
