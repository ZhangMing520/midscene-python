"""Port of upstream packages/core/tests/unit-test/device/*.test.ts."""

from typing import Any

import pytest

SCREEN_SIZE = {"width": 1000, "height": 800}


def _located_at(x: float, y: float) -> dict[str, Any]:
    return {"center": [x, y]}


def _noop(*args: Any, **kwargs: Any) -> None:
    return None


class TestDefineActionsFromInputPrimitives:
    @pytest.mark.asyncio
    async def test_executes_middle_click_at_the_located_point_when_supported(self):
        """executes middle click at the located point when supported"""
        from midscene.core.device import define_actions_from_input_primitives

        calls: list[dict[str, Any]] = []

        actions = define_actions_from_input_primitives(
            {
                "pointer": {
                    "tap": _noop,
                    "middleClick": lambda point: calls.append(point),
                }
            }
        )

        middle_click_action = next(
            (action for action in actions if action.name == "MiddleClick"), None
        )

        assert middle_click_action is not None
        assert middle_click_action.interface_alias == "aiMiddleClick"
        await middle_click_action.execute({"locate": {"center": [12, 34]}})
        assert calls == [{"x": 12, "y": 34}]

    def test_omits_middle_click_on_devices_without_the_primitive(self):
        """omits middle click on devices without the primitive"""
        from midscene.core.device import define_actions_from_input_primitives

        actions = define_actions_from_input_primitives({"pointer": {"tap": _noop}})
        assert not any(action.name == "MiddleClick" for action in actions)

    @pytest.mark.asyncio
    async def test_uses_desktop_guidance_for_a_pointer_swipe(self):
        """uses desktop guidance for a pointer swipe"""
        from midscene.core.device import define_actions_from_input_primitives

        calls: list[tuple] = []

        actions = define_actions_from_input_primitives(
            {
                "pointer": {
                    "tap": _noop,
                    "swipe": lambda start, end, options: calls.append(
                        (start, end, options)
                    ),
                }
            },
            {"size": lambda: {"width": 1920, "height": 1080}},
        )
        swipe_action = next(action for action in actions if action.name == "Swipe")

        assert "primary-mouse-button gesture" in swipe_action.description
        await swipe_action.execute({"direction": "right", "distance": 100})
        assert calls == [
            (
                {"x": 960.0, "y": 540.0},
                {"x": 1060.0, "y": 540.0},
                {"duration": 300},
            )
        ]

    @pytest.mark.asyncio
    async def test_keeps_touch_swipe_behavior_and_guidance_when_both_inputs_exist(
        self,
    ):
        """keeps touch swipe behavior and guidance when both inputs exist"""
        from midscene.core.device import define_actions_from_input_primitives

        pointer_calls: list[tuple] = []
        touch_calls: list[tuple] = []

        actions = define_actions_from_input_primitives(
            {
                "pointer": {
                    "tap": _noop,
                    "swipe": lambda start, end, options: pointer_calls.append(
                        (start, end, options)
                    ),
                },
                "touch": {
                    "swipe": lambda start, end, options: touch_calls.append(
                        (start, end, options)
                    )
                },
            },
            {"size": lambda: {"width": 400, "height": 800}},
        )
        swipe_action = next(action for action in actions if action.name == "Swipe")

        assert "Perform a touch gesture" in swipe_action.description
        await swipe_action.execute({"direction": "up", "distance": 100})
        assert touch_calls == [
            (
                {"x": 200.0, "y": 400.0},
                {"x": 200.0, "y": 300.0},
                {"duration": 300},
            )
        ]
        assert pointer_calls == []

    @pytest.mark.asyncio
    async def test_should_expose_configured_system_input_primitives_as_actions(
        self,
    ):
        """should expose configured system input primitives as actions"""
        from midscene.core.device import define_actions_from_input_primitives

        calls: list[str] = []

        actions = define_actions_from_input_primitives(
            {
                "system": {
                    "backButton": lambda: calls.append("back"),
                    "homeButton": lambda: calls.append("home"),
                    "recentAppsButton": lambda: calls.append("recent"),
                }
            },
            {
                "systemActions": {
                    "backButton": {
                        "name": "AndroidBackButton",
                        "supportedBySystemOne": True,
                        "description": 'Trigger the system "back" operation',
                        "delayBeforeRunner": 0,
                        "delayAfterRunner": 0,
                    },
                    "homeButton": {
                        "name": "AndroidHomeButton",
                        "supportedBySystemOne": True,
                        "description": 'Trigger the system "home" operation',
                        "delayBeforeRunner": 0,
                        "delayAfterRunner": 0,
                    },
                    "recentAppsButton": {
                        "name": "AndroidRecentAppsButton",
                        "supportedBySystemOne": True,
                        "description": 'Trigger the system "recent apps" operation',
                    },
                }
            },
        )

        assert [action.name for action in actions] == [
            "AndroidBackButton",
            "AndroidHomeButton",
            "AndroidRecentAppsButton",
        ]
        assert [action.supported_by_system_one for action in actions] == [
            True,
            True,
            True,
        ]
        assert actions[0].param_schema is None
        assert actions[0].delay_before_runner == 0
        assert actions[0].delay_after_runner == 0

        for action in actions:
            await action.execute()

        assert calls == ["back", "home", "recent"]

    def test_create_default_mobile_actions_keeps_the_upstream_action_order(self):
        """createDefaultMobileActions produces the upstream action order"""
        from midscene.core.device import create_default_mobile_actions

        context = {
            "input": {
                "pointer": {
                    "tap": _noop,
                    "doubleClick": _noop,
                    "rightClick": _noop,
                    "middleClick": _noop,
                    "hover": _noop,
                    "dragAndDrop": _noop,
                    "longPress": _noop,
                },
                "keyboard": {
                    "clearInput": _noop,
                    "typeText": _noop,
                    "keyboardPress": _noop,
                    "cursorMove": _noop,
                },
                "scroll": {"scroll": _noop},
                "touch": {"swipe": _noop, "pinch": _noop},
                "system": {
                    "backButton": _noop,
                    "homeButton": _noop,
                    "recentAppsButton": _noop,
                },
            },
            "size": lambda: {"width": 400, "height": 800},
            "sleep": _noop,
            "systemActions": {
                "backButton": {
                    "name": "AndroidBackButton",
                    "description": "back",
                },
                "homeButton": {
                    "name": "AndroidHomeButton",
                    "description": "home",
                },
                "recentAppsButton": {
                    "name": "AndroidRecentAppsButton",
                    "description": "recent apps",
                },
            },
        }

        names = [action.name for action in create_default_mobile_actions(context)]

        assert names == [
            "Tap",
            "DoubleClick",
            "RightClick",
            "MiddleClick",
            "Hover",
            "DragAndDrop",
            "LongPress",
            "Input",
            "ClearInput",
            "KeyboardPress",
            "CursorMove",
            "Scroll",
            "Swipe",
            "Pinch",
            "AndroidBackButton",
            "AndroidHomeButton",
            "AndroidRecentAppsButton",
        ]

    def test_create_default_mobile_actions_omits_swipe_and_pinch_without_size(self):
        """createDefaultMobileActions requires a size for Swipe and Pinch"""
        from midscene.core.device import create_default_mobile_actions

        names = [
            action.name
            for action in create_default_mobile_actions(
                {"input": {"touch": {"swipe": _noop, "pinch": _noop}}}
            )
        ]

        assert names == []

    def test_input_primitive_options_can_exclude_gestures(self):
        """includeSwipe and includePinch default to true and can be disabled"""
        from midscene.core.device import define_actions_from_input_primitives

        options = {
            "size": lambda: {"width": 400, "height": 800},
            "includeSwipe": False,
            "includePinch": False,
        }
        actions = define_actions_from_input_primitives(
            {"touch": {"swipe": _noop, "pinch": _noop}}, options
        )
        assert [action.name for action in actions] == []


class TestInputActionWithModeOption:
    @staticmethod
    def _create_input_action(clear_calls: list[Any], type_calls: list[tuple]):
        from midscene.core.device import define_action_input

        return define_action_input(
            {
                "clearInput": lambda target: clear_calls.append(target),
                "typeText": lambda value, options: type_calls.append((value, options)),
                "keyboardPress": _noop,
            }
        )

    @pytest.mark.asyncio
    async def test_should_request_replace_when_mode_is_replace(self):
        """should request replace when mode is replace"""
        clear_calls: list[Any] = []
        type_calls: list[tuple] = []
        input_action = self._create_input_action(clear_calls, type_calls)

        await input_action.execute(
            {
                "value": "test value",
                "locate": {"id": "test-id"},
                "mode": "replace",
            }
        )

        assert clear_calls == []
        assert type_calls[0][0] == "test value"
        assert type_calls[0][1]["replace"] is True

    @pytest.mark.asyncio
    async def test_should_only_clear_input_when_mode_is_clear(self):
        """should only clear input when mode is clear"""
        clear_calls: list[Any] = []
        type_calls: list[tuple] = []
        input_action = self._create_input_action(clear_calls, type_calls)

        await input_action.execute(
            {
                "value": "test value",
                "locate": {"id": "test-id"},
                "mode": "clear",
            }
        )

        assert clear_calls == [{"id": "test-id"}]
        assert type_calls == []

    @pytest.mark.asyncio
    async def test_should_skip_clear_input_when_mode_is_type_only(self):
        """should skip clearInput when mode is typeOnly"""
        clear_calls: list[Any] = []
        type_calls: list[tuple] = []
        input_action = self._create_input_action(clear_calls, type_calls)

        await input_action.execute(
            {
                "value": "typed text",
                "locate": {"id": "test-id"},
                "mode": "typeOnly",
            }
        )

        assert clear_calls == []
        assert type_calls[0][0] == "typed text"
        assert type_calls[0][1]["replace"] is False

    @pytest.mark.asyncio
    async def test_should_request_replace_by_default_when_mode_is_not_specified(self):
        """should request replace by default when mode is not specified"""
        clear_calls: list[Any] = []
        type_calls: list[tuple] = []
        input_action = self._create_input_action(clear_calls, type_calls)

        await input_action.execute({"value": "test value", "locate": {"id": "test-id"}})

        assert clear_calls == []
        assert type_calls[0][0] == "test value"
        assert type_calls[0][1]["replace"] is True

    def test_should_validate_the_mode_option_is_in_the_schema(self):
        """should validate the mode option is in the schema"""
        from midscene.core.device import define_action_input

        input_action = define_action_input(
            {
                "clearInput": _noop,
                "typeText": _noop,
                "keyboardPress": _noop,
            }
        )

        schema = input_action.param_schema
        assert schema is not None
        assert "mode" in schema
        assert "typeOnly" in schema["mode"]["type"]


class TestNormalizeMobileSwipeParam:
    cases = [
        {
            "name": "negative distance",
            "param": {"distance": -100, "direction": "right"},
            "message": '"distance" must be a positive number',
        },
        {
            "name": "zero distance",
            "param": {"distance": 0, "direction": "right"},
            "message": '"distance" must be a positive number',
        },
        {
            "name": "non-finite distance",
            "param": {"distance": float("inf"), "direction": "right"},
            "message": '"distance" must be a positive number',
        },
        {
            "name": "missing direction",
            "param": {"distance": 100},
            "message": 'requires both "direction" and a positive "distance"',
        },
        {
            "name": "negative duration",
            "param": {"end": _located_at(600, 400), "duration": -1},
            "message": "duration must be a positive finite number",
        },
        {
            "name": "non-finite duration",
            "param": {"end": _located_at(600, 400), "duration": float("inf")},
            "message": "duration must be a positive finite number",
        },
        {
            "name": "negative repeat",
            "param": {"end": _located_at(600, 400), "repeat": -1},
            "message": "repeat must be a non-negative finite integer",
        },
        {
            "name": "fractional repeat",
            "param": {"end": _located_at(600, 400), "repeat": 1.5},
            "message": "repeat must be a non-negative finite integer",
        },
        {
            "name": "non-finite repeat",
            "param": {"end": _located_at(600, 400), "repeat": float("inf")},
            "message": "repeat must be a non-negative finite integer",
        },
    ]

    def test_normalizes_a_valid_relative_swipe(self):
        """normalizes a valid relative swipe"""
        from midscene.core.device import normalize_mobile_swipe_param

        assert normalize_mobile_swipe_param(
            {
                "start": _located_at(500, 400),
                "distance": 100,
                "direction": "right",
                "duration": 200,
                "repeat": 2,
            },
            SCREEN_SIZE,
        ) == {
            "start_point": {"x": 500, "y": 400},
            "end_point": {"x": 600, "y": 400},
            "duration": 200,
            "repeat_count": 2,
        }

    @pytest.mark.parametrize("case", cases, ids=[case["name"] for case in cases])
    def test_rejects_invalid_parameters(self, case):
        """rejects invalid swipe parameters"""
        from midscene.core.device import normalize_mobile_swipe_param

        with pytest.raises(ValueError, match=case["message"]):
            normalize_mobile_swipe_param(case["param"], SCREEN_SIZE)

    def test_rejects_end_and_distance_together(self):
        """rejects end and distance together"""
        from midscene.core.device import normalize_mobile_swipe_param

        with pytest.raises(ValueError, match="cannot be combined"):
            normalize_mobile_swipe_param(
                {
                    "end": _located_at(600, 400),
                    "distance": 100,
                    "direction": "right",
                },
                SCREEN_SIZE,
            )

    def test_keeps_zero_repeat_as_the_capped_continuous_mode(self):
        """keeps zero repeat as the capped continuous mode"""
        from midscene.core.device import normalize_mobile_swipe_param

        assert (
            normalize_mobile_swipe_param(
                {"end": _located_at(600, 400), "repeat": 0}, SCREEN_SIZE
            )["repeat_count"]
            == 10
        )
