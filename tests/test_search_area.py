"""Synced from upstream packages/core/tests/unit-test/search-area.test.ts."""


class TestDeepLocate:
    def test_expand_search_area(self):
        from midscene.core.ai_model.workflows.grounding.search_area import expand_search_area

        rect = {"left": 500, "top": 500, "width": 50, "height": 30}
        expanded = expand_search_area(rect, {"width": 1000, "height": 1000})
        assert expanded["width"] * expanded["height"] >= 400 * 400

    def test_expand_clamps_to_screen(self):
        from midscene.core.ai_model.workflows.grounding.search_area import expand_search_area

        rect = {"left": 0, "top": 0, "width": 900, "height": 900}
        expanded = expand_search_area(rect, {"width": 1000, "height": 1000})
        assert expanded["left"] == 0
        assert expanded["top"] == 0

    def test_mapping_roundtrip(self):
        from midscene.core.ai_model.workflows.grounding.search_area import (
            map_search_area_result_to_original_result,
        )

        mapping = {"offset": {"x": 100, "y": 50}, "scale": 2}
        result = map_search_area_result_to_original_result(
            {"center": (40, 60), "rect": {"left": 30, "top": 50, "width": 20, "height": 20}},
            mapping,
        )
        assert result["center"] == [120, 80]
        assert result["rect"]["left"] == 115

