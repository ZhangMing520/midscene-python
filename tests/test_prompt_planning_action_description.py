"""Synced from upstream packages/core/tests/unit-test/prompt/planning/
action-description.test.ts."""


class TestPromptActionDescription:
    def test_multiline_action_space_uses_literal_blocks(self):
        from midscene.core.ai_model.prompt.planning import (
            serialize_action_descriptions,
        )

        dumped = serialize_action_descriptions([{"description": "line one\nline two"}])
        assert "|-\n" in dumped
        assert "\\n" not in dumped

    def test_distance_fields_include_input_image_unit_note(self):
        from midscene.core.ai_model.models.registry import get_model_adapter
        from midscene.core.ai_model.prompt.planning import (
            build_standard_planning_system_prompt,
        )
        from midscene.core.device import build_web_action_space

        adapter = get_model_adapter("qwen3-vl")
        prompt = build_standard_planning_system_prompt(
            action_space=build_web_action_space(),
            planning_protocol=adapter.planning_protocol,
            include_locate_in_planning=True,
            locate_prompt_spec=adapter.locate_result_codec.prompt_spec,
        )
        assert (
            "Use pixels of the input image for this distance, even when "
            "position coordinates are normalized." in prompt
        )

    def test_scroll_action_descriptions_match_upstream(self):
        from midscene.core.device import build_android_action_space

        scroll = next(
            action for action in build_android_action_space() if action.name == "Scroll"
        )
        assert "browse content outside the current viewport" in scroll.description
        assert "scrollToBottom/scrollToTop" in scroll.description
        locate_description = scroll.param_schema["locate"]["description"]
        assert (
            'Do NOT provide a general intent like "scroll to find some element"'
            in locate_description
        )
        assert (
            "screen-coordinate units" in scroll.param_schema["distance"]["description"]
        )
        assert (
            "Only effective when scrollType"
            in scroll.param_schema["direction"]["description"]
        )
