"""Synced from upstream packages/core/tests/unit-test/locate-prompt-order.test.ts."""

import pytest

from tests.core_helpers import MockInterface, make_png_base64, patch_model_call


@pytest.fixture
def mock_interface():
    return MockInterface()


class TestLocatePromptOrder:
    def _input(self, references=None):
        return {
            "instructions": "rules",
            "screenshot": "screen",
            "task": "target",
            "references": references or [],
        }

    def test_default_keeps_trailing_references(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(), self._input([reference])
        ) == [
            {"role": "system", "content": "rules"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": "screen"},
                    {"type": "text", "text": "target"},
                ],
            },
            reference,
        ]

    def test_user_each_emits_separate_messages_and_skips_absent_references(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        for layout in (
            "userEach(screenshot:instructions:task:references)",
            "userEach(screenshot:instructions:references:task)",
        ):
            assert build_locate_messages(
                parse_locate_prompt_order(layout), self._input()
            ) == [
                {"role": "user", "content": [{"type": "image", "url": "screen"}]},
                {"role": "user", "content": "rules"},
                {"role": "user", "content": "target"},
            ]

    def test_preserves_reference_boundaries_in_the_middle(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(screenshot:references:instructions:task)"
            ),
            self._input([reference]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            reference,
            {"role": "user", "content": "rules"},
            {"role": "user", "content": "target"},
        ]

    def test_flattens_reference_blocks_and_keeps_group_boundaries(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        reference_image = {"role": "user", "content": [{"type": "image", "url": "ref"}]}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userTogether(screenshot):userTogether(instructions:references:task)"
            ),
            self._input([reference, reference_image]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "rules"},
                    {"type": "text", "text": "reference"},
                    {"type": "image", "url": "ref"},
                    {"type": "text", "text": "target"},
                ],
            },
        ]

    def test_skips_empty_references_only_group(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(instructions):userTogether(references):"
                "userTogether(task:screenshot)"
            ),
            self._input(),
        ) == [
            {"role": "user", "content": "rules"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "target"},
                    {"type": "image", "url": "screen"},
                ],
            },
        ]

    def test_system_can_hold_the_task(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        assert build_locate_messages(
            parse_locate_prompt_order(
                "system(task):userTogether(screenshot:instructions):"
                "userEach(references)"
            ),
            self._input(),
        ) == [
            {"role": "system", "content": "target"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": "screen"},
                    {"type": "text", "text": "rules"},
                ],
            },
        ]

    def test_preserves_text_order_and_system_positions(self):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        for parts, content in (
            ("instructions:task", "rules\n\ntarget"),
            ("task:instructions", "target\n\nrules"),
        ):
            assert build_locate_messages(
                parse_locate_prompt_order(
                    f"system({parts}):userEach(screenshot:references)"
                ),
                self._input(),
            ) == [
                {"role": "system", "content": content},
                {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            ]

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(screenshot):system(task):userEach(references):"
                "system(instructions)"
            ),
            self._input([reference]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            {"role": "system", "content": "target"},
            reference,
            {"role": "system", "content": "rules"},
        ]

    @pytest.mark.parametrize("part", ["screenshot", "references"])
    def test_rejects_image_parts_in_system(self, part):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            parse_locate_prompt_order,
        )

        with pytest.raises(
            ValueError, match=f'system cannot contain image part "{part}"'
        ):
            parse_locate_prompt_order(f"system({part}):userEach(instructions:task)")

    @pytest.mark.parametrize(
        "order",
        [
            "userEach(screenshot):userTogether(task:references:screenshot)",
            "system(task):userEach(instructions:task:screenshot:references)",
            "system(instructions):system(instructions):"
            "userEach(task:screenshot:references)",
            "system():userEach(instructions:task:screenshot:references)",
            "userEach():userTogether(instructions:task:references:screenshot)",
            "userEach(screenshot:task:references)",
            "userEach(instructions:task:references:task)",
            "userEach(instructions:screenshot:task:other)",
        ],
    )
    def test_rejects_invalid_orders(self, order):
        from midscene.core.ai_model.model_adapter.locate_prompt_order import (
            parse_locate_prompt_order,
        )

        with pytest.raises(ValueError, match="Invalid locate promptOrder"):
            parse_locate_prompt_order(order)

    @pytest.mark.asyncio
    async def test_element_locate_respects_prompt_order(self, mock_interface):
        from midscene.core.ai_model.models.registry import ModelAdapter, ModelRuntime
        from midscene.core.ai_model.workflows import ai_locate_element

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [100, 100, 199, 199]}', "usage": None}

        adapter = ModelAdapter(
            "test-prompt-first",
            locate_prompt_order=(
                "system(instructions):userEach(task:screenshot:references)"
            ),
        )
        runtime = ModelRuntime(
            {
                "modelName": "mock-model",
                "modelFamily": "qwen2.5-vl",
                "retryCount": 0,
                "retryInterval": 0,
            },
            adapter,
        )
        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding.locate", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_element("the Submit button", context, runtime)

        messages = captured["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "user",
        ]
        assert "the Submit button" in messages[1]["content"]
        assert messages[2]["content"][0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_section_locate_respects_prompt_order(self, mock_interface):
        from midscene.core.ai_model.models.registry import ModelAdapter, ModelRuntime
        from midscene.core.service import (
            ai_locate_section,
        )

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [0, 0, 500, 500]}', "usage": None}

        adapter = ModelAdapter(
            "test-prompt-first",
            locate_prompt_order=(
                "system(instructions):userEach(task:screenshot:references)"
            ),
        )
        runtime = ModelRuntime(
            {
                "modelName": "mock-model",
                "modelFamily": "gpt-5",
                "retryCount": 0,
                "retryInterval": 0,
            },
            adapter,
        )
        with patch_model_call(
            "midscene.core.service.index", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_section(context, "the row containing Apollo", runtime)

        messages = captured["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "user",
        ]
        assert "the row containing Apollo" in messages[1]["content"]
        assert messages[2]["content"][0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_element_locate_appends_reference_images(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_locate_element

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [100, 100, 199, 199]}', "usage": None}

        png = "data:image/png;base64," + make_png_base64()
        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding.locate", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_element(
                {
                    "prompt": "the Submit button",
                    "images": [{"name": "ref", "url": png}],
                },
                context,
                _make_runtime(modelFamily="qwen2.5-vl"),
            )

        messages = captured["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        reference_messages = messages[2:]
        assert "reference images" in reference_messages[0]["content"][0]["text"]
        assert "named 'ref'" in reference_messages[1]["content"][0]["text"]
        assert reference_messages[2]["content"][0] == {
            "type": "image",
            "url": png,
        }



def _make_runtime(**overrides):
    from midscene.core.ai_model.models.registry import get_model_runtime

    config = {
        "modelName": "mock-model",
        "intent": "locate",
        "slot": "locate",
        "modelFamily": "gpt-5",
        "retryCount": 0,
        "retryInterval": 0,
        "responseFormat": "none",
    }
    config.update(overrides)
    return get_model_runtime(config)
