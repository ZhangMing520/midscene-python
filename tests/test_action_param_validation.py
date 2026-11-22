"""Synced from upstream packages/core/tests/unit-test/action-param-validation.test.ts."""

import pytest


class TestActionParamValidation:
    @pytest.mark.asyncio
    async def test_input_drops_unsupported_options(self):
        from midscene.core.device import _execute_input

        class InputDevice:
            def __init__(self):
                self.typed = None

            async def input_text(self, text):
                self.typed = text

        device = InputDevice()
        await _execute_input(
            {"value": "hi", "keyboardTypeDelay": 10, "inputStrategy": "bulk"},
            device,
            None,
        )
        assert device.typed == "hi"

