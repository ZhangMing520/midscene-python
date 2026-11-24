"""Synced from upstream packages/core/tests/unit-test/model-adapter/ui-tars/
actions.test.ts and planning-response-parser.test.ts."""

import json

import pytest


class TestUiTars:
    def test_parse_action_call(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_ui_tars_action_calls,
        )

        raw = "Thought: click the button\nAction: click(start_box='[500,300,600,340]')"
        actions = parse_ui_tars_action_calls(raw)
        assert actions[0]["action_type"] == "click"
        # [500,300,600,340] / 1000 -> [0.5,0.3,0.6,0.34]
        box = json.loads(actions[0]["action_inputs"]["start_box"])
        assert box == pytest.approx([0.5, 0.3, 0.6, 0.34], abs=1e-6)
        assert actions[0]["thought"] == "click the button"

    def test_transform_click(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
        )

        parsed = {
            "actions": parse_ui_tars_action_calls(
                "Thought: tap it\nAction: click(start_box='[250,150]')"
            )
        }
        transformed, unhandled = transform_ui_tars_actions(parsed)
        assert unhandled == []
        assert transformed[0]["type"] == "Tap"
        point = transformed[0]["param"]["locate"]["point"]
        assert point == pytest.approx((0.25, 0.15), abs=1e-6)

    def test_transform_hotkey(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            _transform_hotkey_input,
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
        )

        assert _transform_hotkey_input("ctrl a") == ["Control", "a"]
        assert _transform_hotkey_input("enter") == ["Enter"]

        parsed = {
            "actions": parse_ui_tars_action_calls(
                "Thought: submit\nAction: hotkey(key='Return')"
            )
        }
        transformed, _ = transform_ui_tars_actions(parsed)
        assert transformed[0]["type"] == "KeyboardPress"
        assert transformed[0]["param"]["keyName"] == "Enter"

    def test_transform_finished(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
        )

        parsed = {
            "actions": parse_ui_tars_action_calls(
                'Thought: done\nAction: finished(content="task completed")'
            )
        }
        transformed, _ = transform_ui_tars_actions(parsed)
        assert transformed[0]["type"] == "Finished"
        assert transformed[0]["thought"] == "task completed"

    def test_bbox_conversion(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_ui_tars_action_calls,
        )

        raw = "Action: click(start_box='<bbox>100 200 300 400</bbox>')"
        actions = parse_ui_tars_action_calls(raw)
        box = json.loads(actions[0]["action_inputs"]["start_box"])
        # center of (100,200)-(300,400) = (200,300) -> /1000
        assert box == pytest.approx([0.2, 0.3, 0.2, 0.3], abs=1e-6)


def test_ui_tars_get_summary_strips_reflection():
    from midscene.core.ai_model.models.ui_tars.prompt import get_summary

    prediction = (
        "Reflection: I should click the button. "
        "Action_Summary: Click the submit button. "
        "Action: click(start_box='[500,300,600,340]')"
    )
    assert get_summary(prediction) == (
        "Action_Summary: Click the submit button. "
        "Action: click(start_box='[500,300,600,340]')"
    )
