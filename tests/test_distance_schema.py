"""Synced from upstream packages/core/tests/unit-test/distance-schema.test.ts."""

from midscene.core.common import parse_action_param
from midscene.core.device import DeviceAction


def test_uses_metadata_rather_than_action_parameter_names_and_leaves_durations_untouched():
    action = DeviceAction(
        name="Scroll", description="", distance_fields=["distance"]
    )

    parsed = parse_action_param(
        {"distance": 100},
        action,
        {
            "distanceUnit": "model-input-image-pixel",
            "shrunkShotToLogicalRatio": 2,
        },
    )

    assert parsed == {"distance": 50}
    assert parse_action_param({"x": 1}, None) is None
