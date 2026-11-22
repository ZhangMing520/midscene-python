"""Port of upstream packages/core/tests/unit-test/input-strategy.test.ts."""

import math
from typing import List

import pytest


class TestTextInputStrategy:
    def test_defaults_to_legacy(self):
        """defaults to legacy"""
        from midscene.core.device.input_strategy import resolve_input_strategy

        assert resolve_input_strategy() == "legacy"

    def test_rejects_an_unsupported_runtime_strategy(self):
        """rejects an unsupported runtime strategy"""
        from midscene.core.device.input_strategy import resolve_input_strategy

        with pytest.raises(
            ValueError,
            match=(
                "inputStrategy must be one of: legacy, sequential, bulk; "
                "received paste"
            ),
        ):
            resolve_input_strategy("paste")
        with pytest.raises(
            ValueError,
            match=(
                "inputStrategy must be one of: legacy, sequential, bulk; "
                "received null"
            ),
        ):
            resolve_input_strategy(None)

    def test_rejects_bulk_input_with_a_positive_keyboard_delay(self):
        """rejects bulk input with a positive keyboard delay"""
        from midscene.core.device.input_strategy import resolve_input_strategy

        with pytest.raises(
            ValueError,
            match=(
                'inputStrategy "bulk" requires keyboardTypeDelay to be omitted '
                'or set to 0; use inputStrategy "sequential" for delayed input'
            ),
        ):
            resolve_input_strategy("bulk", 1)

    def test_allows_bulk_input_with_zero_delay(self):
        """allows bulk input with zero delay"""
        from midscene.core.device.input_strategy import resolve_input_strategy

        assert resolve_input_strategy("bulk", 0) == "bulk"

    @pytest.mark.parametrize(
        "keyboard_type_delay",
        [-1, math.nan, -math.inf, math.inf],
        ids=["negative", "nan", "negative-infinity", "positive-infinity"],
    )
    def test_rejects_invalid_keyboard_delay(self, keyboard_type_delay):
        """rejects invalid keyboard delay"""
        from midscene.core.device.input_strategy import resolve_input_strategy

        with pytest.raises(
            ValueError,
            match="keyboardTypeDelay must be a finite non-negative number",
        ):
            resolve_input_strategy("legacy", keyboard_type_delay)

    def test_resolves_action_options_over_platform_defaults(self):
        """resolves action options over platform defaults"""
        from midscene.core.device.input_strategy import resolve_text_input_options

        assert resolve_text_input_options(
            {"inputStrategy": "bulk", "keyboardTypeDelay": 0},
            {"inputStrategy": "sequential", "keyboardTypeDelay": 80},
        ) == {"input_strategy": "bulk", "keyboard_type_delay": 0}

    def test_preserves_platform_defaults_when_action_options_are_omitted(self):
        """preserves platform defaults when action options are omitted"""
        from midscene.core.device.input_strategy import resolve_text_input_options

        assert resolve_text_input_options(
            None,
            {"inputStrategy": "sequential", "keyboardTypeDelay": 0},
        ) == {"input_strategy": "sequential", "keyboard_type_delay": 0}

    def test_identifies_legacy_delayed_and_explicit_sequential_input(self):
        """identifies legacy delayed and explicit sequential input"""
        from midscene.core.device.input_strategy import should_input_sequentially

        assert should_input_sequentially(
            {"inputStrategy": "legacy", "keyboardTypeDelay": 1}
        )
        assert should_input_sequentially(
            {"inputStrategy": "sequential", "keyboardTypeDelay": 0}
        )
        assert not should_input_sequentially(
            {"inputStrategy": "legacy", "keyboardTypeDelay": 0}
        )

    @pytest.mark.asyncio
    async def test_sends_unicode_code_points_in_order_and_waits_only_between_them(self):
        """sends Unicode code points in order and waits only between them"""
        from midscene.core.device.input_strategy import send_text_sequentially

        characters: List[str] = []
        waits: List[int] = []

        await send_text_sequentially(
            "A😀B",
            {
                "sendCharacter": lambda character: characters.append(character),
                "wait": lambda delay: waits.append(delay),
            },
            {"delayMs": 25},
        )

        assert characters == ["A", "😀", "B"]
        assert waits == [25, 25]

    @pytest.mark.asyncio
    async def test_can_preserve_a_legacy_trailing_delay_explicitly(self):
        """can preserve a legacy trailing delay explicitly"""
        from midscene.core.device.input_strategy import send_text_sequentially

        waits: List[int] = []

        await send_text_sequentially(
            "AB",
            {"sendCharacter": lambda character: None, "wait": waits.append},
            {"delayMs": 10, "delayAfterLast": True},
        )

        assert len(waits) == 2
