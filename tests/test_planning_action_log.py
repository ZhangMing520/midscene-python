"""Synced from upstream packages/core/tests/unit-test/workflows/planning/planning-action-log.test.ts."""

from midscene.core.common import dump_action_param
from midscene.core.device import DeviceAction


def test_keeps_non_locator_parameters_and_replaces_locator_results_with_prompts():
    action = DeviceAction(
        name="Tap",
        description="",
        locate_fields=["locate"],
        interface_alias="aiTap",
    )
    assert dump_action_param({"locate": {"prompt": "login"}}, action) == {
        "locate": "login"
    }
    prompt = {"prompt": "login", "images": [{"name": "a", "url": "b"}]}
    assert dump_action_param({"locate": {"prompt": prompt}}, action) == {
        "locate": "login (with 1 image)"
    }
