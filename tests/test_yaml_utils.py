"""Synced from upstream packages/web-integration/tests/unit-test/yaml/utils.test.ts."""

import pytest


class TestYamlUtils:
    def test_parse_script(self):
        from midscene.core.yaml import parse_yaml_script

        script = parse_yaml_script(
            """
web:
  url: https://example.com
tasks:
  - name: flow
    flow:
      - aiAction: click the button
      - sleep: 100
"""
        )
        assert script["web"]["url"] == "https://example.com"
        assert script["tasks"][0]["flow"][0]["aiAction"] == "click the button"

    def test_computer_env_is_a_target(self):
        from midscene.core.yaml import parse_yaml_script

        script = parse_yaml_script(
            "computer:\n  displayId: '1'\n"
            "tasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
        )
        assert script["computer"]["displayId"] == "1"

    def test_computer_and_web_are_mutually_exclusive(self):
        from midscene.core.yaml import parse_yaml_script

        with pytest.raises(ValueError, match="only one of"):
            parse_yaml_script(
                "web:\n  url: https://example.com\ncomputer: {}\n"
                "tasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
            )

    def test_env_interpolation(self):
        import os

        from midscene.core.yaml import parse_yaml_script

        os.environ["MIDSCENE_TEST_URL"] = "https://env-example.com"
        script = parse_yaml_script(
            """
web:
  url: ${MIDSCENE_TEST_URL}
tasks:
  - name: t
    flow:
      - sleep: 10
"""
        )
        assert script["web"]["url"] == "https://env-example.com"

    def test_resolve_yaml_output_config_prefers_target_values(self):
        from midscene.core.yaml.utils import resolve_yaml_output_config

        web_config = resolve_yaml_output_config(
            {
                "web": {"output": "./target-output", "unstableLogContent": True},
                "config": {"output": "./config-output"},
            }
        )
        assert web_config == {
            "output": "./target-output",
            "unstableLogContent": True,
        }

        fallback = resolve_yaml_output_config(
            {
                "computer": {"output": "./computer-output"},
                "config": {"output": "./config-output", "unstableLogContent": False},
            }
        )
        assert fallback == {
            "output": "./computer-output",
            "unstableLogContent": False,
        }
