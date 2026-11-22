"""Synced from upstream packages/core/tests/unit-test/model-adapter/auto-glm/
actions.test.ts, planning-action-parser.test.ts and response-parser.test.ts."""

import pytest


class TestAutoGlm:
    def test_parse_response_split(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_auto_glm_response,
        )

        response = parse_auto_glm_response(
            '<think>look around</think><answer>do(action="Tap", element=[123,456])</answer>'
        )
        # Upstream priority: the do(action=) branch wins over <answer>, and it
        # keeps both the <think> tags and the trailing </answer> (faithful).
        assert response["think"] == "<think>look around</think><answer>"
        assert response["content"] == 'do(action="Tap", element=[123,456])</answer>'

    def test_parse_tap_action(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {"think": "t", "content": 'do(action="Tap", element=[100,200])'}
        )
        assert action == {"_metadata": "do", "action": "Tap", "element": (100, 200), "think": "t"}

    def test_parse_finish_with_escaped_quotes(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {
                "think": "",
                "content": 'finish(message="Finished! There is a contact whose name is \\"Tom\\" in the list.")',
            }
        )
        assert action["_metadata"] == "finish"
        assert "Tom" in action["message"]

    def test_parse_wait_duration(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {"think": "", "content": 'do(action="Wait", duration="3 seconds")'}
        )
        assert action["durationMs"] == 3000

    def test_transform_swipe_inverts_direction(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            transform_auto_glm_action,
        )

        def distance_to_pixels(delta, axis):
            return round(abs(delta))

        actions = transform_auto_glm_action(
            {
                "_metadata": "do",
                "action": "Swipe",
                "start": (500, 200),
                "end": (500, 800),
                "think": "swipe",
            },
            [],
            distance_to_pixels,
        )
        # finger moved down -> content scrolls -> direction 'up'
        assert actions[0]["type"] == "Scroll"
        assert actions[0]["param"]["direction"] == "up"
        assert actions[0]["param"]["distance"] == 600

    def test_transform_finish(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            transform_auto_glm_action,
        )

        actions = transform_auto_glm_action(
            {"_metadata": "finish", "message": "all done"}, [], None
        )
        assert actions[0]["type"] == "Finished"
        assert actions[0]["thought"] == "all done"

    def test_transform_unsupported_raises(self):
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            transform_auto_glm_action,
        )

        with pytest.raises(ValueError) as exc:
            transform_auto_glm_action(
                {"_metadata": "do", "action": "Interact"}, [], None
            )
        assert "not supported" in str(exc.value)

