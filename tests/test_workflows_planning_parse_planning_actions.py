"""Synced from upstream packages/core/tests/unit-test/workflows/planning/parse-planning-actions.test.ts."""

import pytest

from midscene.core.ai_model.workflows.planning.parse_planning_actions import (
    parse_planning_actions,
)
from midscene.core.common import (
    parse_action_param,
    validate_required_locate_fields,
)
from midscene.core.device import DeviceAction


def _action_space():
    return [
        DeviceAction(name="Back", description="Go back"),
        DeviceAction(
            name="Tap",
            description="Tap",
            param_schema={"locate": {"type": "locate"}},
            locate_fields=["locate"],
        ),
        DeviceAction(
            name="Scroll",
            description="Scroll",
            param_schema={
                "locate": {"type": "locate", "optional": True},
                "distance": {"type": "number", "optional": True},
            },
            locate_fields=["locate"],
            distance_fields=["distance"],
        ),
    ]


def _parse(actions, action_space):
    parse_planning_actions(
        actions,
        action_space=action_space,
        parse_raw_locate_parameter=lambda value: value,
        include_locate_in_planning=False,
        locate_result_context={"preparedSize": {"width": 100, "height": 100}},
    )


def _assert_raises(callable_, expected):
    with pytest.raises(ValueError) as exc_info:
        callable_()
    assert expected in str(exc_info.value)


@pytest.mark.parametrize("locate", [0, False, "", None])
def test_rejects_invalid_optional_locators(locate):
    """rejects invalid optional locators: %j"""
    _assert_raises(
        lambda: _parse(
            [{"type": "Scroll", "param": {"locate": locate}}], _action_space()
        ),
        "Invalid parameters for action Scroll: locate: "
        "Expected an object with a prompt field",
    )


def test_allows_an_explicitly_undefined_optional_locator():
    """allows an explicitly undefined optional locator"""
    # Python represents an undefined field by omitting the key.
    actions = [{"type": "Scroll", "param": {}}]
    _parse(actions, _action_space())
    assert actions[0]["param"] == {}


def test_allows_omitted_parameters_for_parameterless_actions_and_optional_default_fields():
    """allows omitted parameters for parameterless actions and optional/default fields"""
    actions = [{"type": "Back"}, {"type": "Scroll"}]
    _parse(actions, _action_space())
    assert actions == [{"type": "Back"}, {"type": "Scroll"}]


def test_preserves_parameter_identity_and_discards_coordinates_in_prompt_only_mode():
    """preserves parameter identity and discards coordinates in prompt-only mode"""
    param = {
        "locate": {
            "prompt": "submit",
            "bbox": [10, 20, 30, 40],
        }
    }
    actions = [{"type": "Tap", "param": param}]
    _parse(actions, _action_space())
    assert actions[0]["param"] is param
    assert param == {"locate": {"prompt": "submit"}}


@pytest.mark.parametrize(
    "param", [None, {}, {"locate": None}, {"locate": {"prompt": 123}}]
)
def test_rejects_invalid_required_locators(param):
    """rejects invalid required locators: %j"""
    _assert_raises(
        lambda: _parse([{"type": "Tap", "param": param}], _action_space()),
        "Invalid parameters for action Tap: locate",
    )


@pytest.mark.parametrize(
    "param",
    [
        {"value": "hello"},
        {"value": "hello", "count": "2"},
        {"value": 123},
        {"value": "hello", "count": -1},
        {},
    ],
)
def test_shares_execution_validation_for_ordinary_parameters(param):
    """shares execution validation for ordinary parameters: %j"""
    definition = DeviceAction(
        name="Input",
        description="Input",
        param_schema={
            "value": {"type": "string"},
            "count": {"type": "number", "optional": True},
        },
    )

    def accepts(validate):
        try:
            validate()
            return True
        except Exception:
            return False

    assert accepts(
        lambda: _parse([{"type": "Input", "param": param}], [definition])
    ) == accepts(lambda: parse_action_param(param, definition))


@pytest.mark.skip(
    reason="Upstream relies on zod defaults/transforms; Python parse_action_param "
    "returns raw params without applying schema defaults."
)
def test_preserves_raw_parameters_during_preflight_and_applies_defaults_at_execution():
    """preserves raw parameters during preflight and applies defaults at execution"""


@pytest.mark.skip(
    reason="Upstream relies on zod field refinements; Python action param schemas "
    "are plain dicts without refinement validation."
)
def test_shares_ordinary_field_refinements_when_a_locator_is_present():
    """shares ordinary field refinements when a locator is present"""


@pytest.mark.parametrize(
    "locate",
    [{"prompt": "submit"}, {"prompt": "submit", "bbox": [10, 20, 30, 40]}],
)
def test_accepts_planning_locators_before_execution_resolves_them(locate):
    """accepts planning locators before execution resolves them: %j"""
    _parse([{"type": "Tap", "param": {"locate": locate}}], _action_space())
    resolved = {
        "center": [20, 30],
        "description": "submit",
        "rect": {"left": 10, "top": 20, "width": 21, "height": 21},
    }
    tap_definition = _action_space()[1]
    assert parse_action_param(
        {"locate": resolved},
        tap_definition,
        {"shrunkShotToLogicalRatio": 2},
    )["locate"]["center"] == [10, 15]


@pytest.mark.parametrize(
    "locate",
    [{}, {"bbox": [10, 20, 30, 40]}, {"locatedPixelResult": {"center": [20, 30]}}],
)
def test_requires_a_model_facing_prompt(locate):
    """requires a model-facing prompt: %j"""
    _assert_raises(
        lambda: _parse(
            [{"type": "Tap", "param": {"locate": locate}}], _action_space()
        ),
        "Invalid parameters for action Tap: locate.prompt: Required",
    )


def test_discards_extra_locator_options_and_coordinates_in_prompt_only_mode():
    """discards extra locator options and coordinates in prompt-only mode"""
    locate = {
        "prompt": "submit",
        "deepLocate": "not a boolean",
        "cacheable": "not a boolean",
        "xpath": 123,
        "bbox": ["invalid"],
    }
    actions = [{"type": "Tap", "param": {"locate": locate}}]
    _parse(actions, _action_space())
    assert actions[0]["param"]["locate"] == {"prompt": "submit"}


@pytest.mark.parametrize("prompt", ["submit", {"prompt": "submit"}])
def test_accepts_supported_prompt_values(prompt):
    """accepts supported prompt values: %j"""
    _parse(
        [{"type": "Tap", "param": {"locate": {"prompt": prompt}}}],
        _action_space(),
    )


@pytest.mark.parametrize("prompt", [123, None, {}, {"prompt": 123}])
def test_rejects_invalid_prompt_values(prompt):
    """rejects invalid prompt values: %j"""
    _assert_raises(
        lambda: _parse(
            [{"type": "Tap", "param": {"locate": {"prompt": prompt}}}],
            _action_space(),
        ),
        "Invalid parameters for action Tap: locate.prompt",
    )


def test_rejects_a_string_locator_instead_of_treating_it_as_a_prompt():
    """rejects a string locator instead of treating it as a prompt"""
    _assert_raises(
        lambda: _parse(
            [{"type": "Tap", "param": {"locate": "submit"}}], _action_space()
        ),
        "locate: Expected an object with a prompt field",
    )


def test_rejects_a_locator_using_an_unsupported_prompt_field():
    """rejects a locator using an unsupported prompt field"""
    actions = [{"type": "Tap", "param": {"locate": {"label": "submit"}}}]
    _assert_raises(
        lambda: _parse(actions, _action_space()),
        "locate.prompt: Required",
    )
    assert actions[0]["param"]["locate"] == {"label": "submit"}


@pytest.mark.parametrize("param", [None, {}, {"locate": None}, {"locate": ""}])
def test_shares_required_locator_checks_with_task_construction(param):
    """shares required locator checks with task construction: %j"""
    tap_definition = _action_space()[1]
    _assert_raises(
        lambda: validate_required_locate_fields(param, tap_definition),
        "locate: Required",
    )
    _assert_raises(
        lambda: _parse([{"type": "Tap", "param": param}], _action_space()),
        "locate: Required",
    )


def test_rejects_unknown_actions():
    """rejects unknown actions"""
    _assert_raises(
        lambda: _parse([{"type": "Unknown"}], _action_space()),
        "Action type 'Unknown' is not in the current action space",
    )
