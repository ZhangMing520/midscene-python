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

