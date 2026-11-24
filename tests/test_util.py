"""Synced from upstream
``packages/web-integration/tests/unit-test/util.test.ts``.

The upstream test covers ``getKeyCommands`` from web-page.ts and
``buildDetailedLocateParam``/``buildDetailedLocateParamAndRestParams`` from
core/yaml.ts; the Python counterparts live in
``midscene.web_integration.web_page`` and ``midscene.core.yaml.utils``.
"""

import sys

from midscene.core.yaml.utils import (
    build_detailed_locate_param,
    build_detailed_locate_param_and_rest_params,
)
from midscene.web_integration.web_page import (
    build_key_commands,
    get_key_commands,
)


def test_should_return_a_single_key_without_command_when_no_meta_or_control_key_is_provided():
    """should return a single key without command when no meta or control key is provided"""
    result = get_key_commands("a")
    assert result == [{"key": "A"}]


def test_should_work_with_array_input_without_meta_key():
    """should work with array input without meta key"""
    result = get_key_commands(["b", "d"])
    assert result == [{"key": "B"}, {"key": "D"}]


def test_should_attach_select_all_command_when_meta_is_present_with_key_a():
    '''should attach "SelectAll" command when "Meta" is present with key "a"'''
    result = get_key_commands(["Meta", "a", "b"])
    assert result == [
        {"key": "Meta"},
        {"key": "A", "command": "SelectAll"},
        {"key": "B"},
    ]


def test_should_attach_copy_command_when_control_is_present_with_key_c():
    '''should attach "Copy" command when "Control" is present with key "c"'''
    result = get_key_commands(["Control", "c", "x"])
    assert result == [
        {"key": "Control"},
        {"key": "C", "command": "Copy"},
        {"key": "X"},
    ]


def test_should_attach_proper_commands_for_uppercase_letters_when_meta_is_present():
    """should attach proper commands for uppercase letters when "Meta" is present"""
    result = get_key_commands(["Meta", "A", "C", "V"])
    assert result == [
        {"key": "Meta"},
        {"key": "A", "command": "SelectAll"},
        {"key": "C", "command": "Copy"},
        {"key": "V", "command": "Paste"},
    ]


def test_should_support_ctrl_a_combination_string():
    """should support ctrl+a combination string"""
    result = build_key_commands("Ctrl+A")
    if sys.platform == "darwin":
        assert result == [
            {"key": "Meta"},
            {"key": "A", "command": "SelectAll"},
        ]
    else:
        assert result == [
            {"key": "Control"},
            {"key": "A", "command": "SelectAll"},
        ]


def test_should_support_ctrl_a_combination_with_spaces():
    """should support ctrl + a combination with spaces"""
    result = build_key_commands("Ctrl + A")
    if sys.platform == "darwin":
        assert result == [
            {"key": "Meta"},
            {"key": "A", "command": "SelectAll"},
        ]
    else:
        assert result == [
            {"key": "Control"},
            {"key": "A", "command": "SelectAll"},
        ]


def test_should_build_basic_detailed_locate_param_from_string_prompt():
    """should build basic detailed locate param from string prompt"""
    locate_prompt = "Click on the login button"
    result = build_detailed_locate_param(locate_prompt)

    assert result == {
        "prompt": "Click on the login button",
        "deepLocate": False,
        "cacheable": True,
        "xpath": None,
    }


def test_should_build_detailed_locate_param_with_options():
    """should build detailed locate param with options"""
    locate_prompt = "Find the submit button"
    options = {
        "deepLocate": True,
        "cacheable": False,
        "xpath": '//button[@type="submit"]',
    }
    result = build_detailed_locate_param(locate_prompt, options)

    assert result == {
        "cacheable": False,
        "deepLocate": True,
        "prompt": "Find the submit button",
        "xpath": '//button[@type="submit"]',
    }


def test_should_handle_partial_options_with_defaults():
    """should handle partial options with defaults"""
    locate_prompt = "Locate the search input"
    options = {"deepLocate": True}
    result = build_detailed_locate_param(locate_prompt, options)

    assert result == {
        "prompt": "Locate the search input",
        "deepLocate": True,
        "cacheable": True,  # default value
        "xpath": None,  # default value
    }


def test_should_unwrap_prompt_only_object_prompts_to_avoid_double_nesting():
    """should unwrap prompt-only object prompts to avoid double nesting"""
    locate_prompt = {
        "prompt": "Please determine whether there is a specific on the page.",
    }

    result = build_detailed_locate_param(locate_prompt)

    assert result == {
        "prompt": "Please determine whether there is a specific on the page.",
        "deepLocate": False,
        "cacheable": True,
        "xpath": None,
    }


def test_should_build_detailed_locate_param_and_empty_rest_params_when_no_extra_options():
    """should build detailed locate param and empty rest params when no extra options"""
    locate_prompt = "Click on the login button"
    result = build_detailed_locate_param_and_rest_params(locate_prompt, None)

    assert result["locateParam"] == {
        "prompt": "Click on the login button",
        "deepLocate": False,
        "cacheable": True,
        "xpath": None,
    }
    assert result["restParams"] == {}


def test_should_build_detailed_locate_param_and_extract_ui_context_to_rest_params():
    """should build detailed locate param and extract uiContext to restParams"""
    locate_prompt = "Find the submit button"
    mock_page_context = {
        "tree": {"node": None, "children": []},
        "shotSize": {"width": 800, "height": 600},
        "shrunkShotToLogicalRatio": 1,
        "screenshot": "mock-base64-string",
    }
    options = {
        "deepLocate": True,
        "cacheable": False,
        "xpath": '//button[@type="submit"]',
        "prompt": "Override prompt",
        "uiContext": mock_page_context,
    }
    result = build_detailed_locate_param_and_rest_params(locate_prompt, options)

    assert result["locateParam"] == {
        "cacheable": False,
        "deepLocate": True,
        "prompt": "Find the submit button",
        "xpath": '//button[@type="submit"]',
    }
    assert result["restParams"] == {"uiContext": mock_page_context}


def test_should_handle_multiple_rest_params():
    """should handle multiple rest params"""
    locate_prompt = "Locate the search input"
    options = {
        "deepLocate": True,
        "uiContext": {
            "tree": {"node": None, "children": []},
            "shotSize": {"width": 1024, "height": 768},
            "shrunkShotToLogicalRatio": 1,
            "screenshotBase64": "mock-base64-string",
        },
        "customParam1": "value1",
        "customParam2": 42,
        "customParam3": True,
    }
    result = build_detailed_locate_param_and_rest_params(locate_prompt, options)

    assert result["locateParam"] == {
        "prompt": "Locate the search input",
        "deepLocate": True,
        "cacheable": True,
        "xpath": None,
    }
    assert result["restParams"] == {
        "uiContext": {
            "tree": {"node": None, "children": []},
            "shotSize": {"width": 1024, "height": 768},
            "shrunkShotToLogicalRatio": 1,
            "screenshotBase64": "mock-base64-string",
        },
        "customParam1": "value1",
        "customParam2": 42,
        "customParam3": True,
    }


def test_should_handle_null_options():
    """should handle null options"""
    locate_prompt = "Test prompt"
    result = build_detailed_locate_param_and_rest_params(locate_prompt, None)

    assert result["locateParam"] == {
        "prompt": "Test prompt",
        "deepLocate": False,
        "cacheable": True,
        "xpath": None,
    }
    assert result["restParams"] == {}
