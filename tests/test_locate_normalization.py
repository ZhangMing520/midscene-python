"""Synced from upstream packages/core/tests/unit-test/locate-normalization.test.ts."""

import pytest


class TestPlanningLocateNormalization:
    def _codec(self):
        from midscene.core.ai_model.models.registry import GPT_LOCATE_FORMAT
        from midscene.core.ai_model.shared.model_locate_result import create_locate_result_codec

        return create_locate_result_codec(GPT_LOCATE_FORMAT)

    def test_prompt_only_when_not_included(self):
        from midscene.core.ai_model.workflows.planning.standard_planning import (
            normalize_planning_locate_parameter,
        )

        normalized = normalize_planning_locate_parameter(
            {"prompt": "button", "bbox": [1, 2, 3, 4]},
            self._codec(),
            {"preparedSize": {"width": 320, "height": 240}},
            False,
        )
        assert normalized == {"prompt": "button"}

    def test_coordinates_are_converted_and_removed(self):
        from midscene.core.ai_model.workflows.planning.standard_planning import (
            normalize_planning_locate_parameter,
        )

        normalized = normalize_planning_locate_parameter(
            {"prompt": "button", "bbox": [190, 115, 210, 135]},
            self._codec(),
            {"preparedSize": {"width": 320, "height": 240}},
            True,
        )
        assert "bbox" not in normalized
        assert normalized["locatedPixelResult"]["center"] == (200.0, 125.0)

    def test_missing_coordinates_raise(self):
        from midscene.core.ai_model.workflows.planning.standard_planning import (
            normalize_planning_locate_parameter,
        )

        with pytest.raises(ValueError):
            normalize_planning_locate_parameter(
                {"prompt": "button"},
                self._codec(),
                {"preparedSize": {"width": 320, "height": 240}},
                True,
            )



class TestNormalizePlanningActionFields:
    def _codec(self):
        from midscene.core.ai_model.models.registry import GPT_LOCATE_FORMAT
        from midscene.core.ai_model.shared.model_locate_result import (
            create_locate_result_codec,
        )

        return create_locate_result_codec(GPT_LOCATE_FORMAT)

    def test_normalizes_declared_locate_fields_in_place(self):
        from midscene.core.ai_model.workflows.planning.locate_normalization import (
            normalize_planning_action_fields,
        )

        codec = self._codec()
        actions = [
            {
                "type": "Tap",
                "param": {"locate": {"prompt": "submit", "bbox": [100, 200, 300, 400]}},
            },
            {
                "type": "Unknown",
                "param": {"locate": {"prompt": "ignored", "bbox": [1, 2, 3, 4]}},
            },
        ]
        action_space = [{"name": "Tap", "locate_fields": ["locate"]}]

        normalize_planning_action_fields(
            actions,
            action_space,
            include_locate_in_planning=True,
            locate_result_codec=codec,
            locate_result_context={
                "preparedSize": {"width": 1000, "height": 1000},
                "contentSize": {"width": 1000, "height": 1000},
            },
        )

        assert actions[0]["param"]["locate"] == {
            "prompt": "submit",
            "locatedPixelResult": {
                "center": (200, 300),
                "rect": {"left": 100, "top": 200, "width": 200, "height": 200},
            },
        }
        assert actions[1]["param"]["locate"] == {
            "prompt": "ignored",
            "bbox": [1, 2, 3, 4],
        }

    def test_keeps_only_prompt_when_locate_is_not_in_planning(self):
        from midscene.core.ai_model.workflows.planning.locate_normalization import (
            normalize_planning_action_fields,
        )

        actions = [{"type": "Tap", "param": {"locate": {"prompt": "submit", "bbox": [1, 2, 3, 4]}}}]
        normalize_planning_action_fields(
            actions,
            [{"name": "Tap", "locate_fields": ["locate"]}],
            include_locate_in_planning=False,
            locate_result_codec=self._codec(),
            locate_result_context={
                "preparedSize": {"width": 1000, "height": 1000},
            },
        )
        assert actions[0]["param"]["locate"] == {"prompt": "submit"}
