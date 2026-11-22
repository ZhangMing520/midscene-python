"""Synced from upstream packages/core/tests/unit-test/device-options.test.ts.

The upstream file only asserts TypeScript type definitions: every case builds
an object literal and checks ``expect(options).toBeDefined()`` (the real check
is compile-time). Python has no equivalent static device-option contract
(``midscene.core.device.device_options`` only holds kwargs-filtering helpers),
so the runtime assertions cannot be reproduced without replacing them with
no-op checks. Each upstream case is kept below and skipped for that reason.
"""

import pytest

_SKIP = pytest.mark.skip(
    reason="upstream case asserts TypeScript type definitions only; the Python "
    "port has no runtime device-option type contract to verify"
)


@_SKIP
def test_should_include_all_required_android_device_options():
    """should include all required Android device options"""
    pass


@_SKIP
def test_android_should_work_with_partial_options():
    """should work with partial options"""
    pass


@_SKIP
def test_android_device_input_opt_should_include_keyboard_options():
    """AndroidDeviceInputOpt should include keyboard options"""
    pass


@_SKIP
def test_should_include_all_required_ios_device_options():
    """should include all required iOS device options"""
    pass


@_SKIP
def test_should_reject_unsupported_device_selectors():
    """should reject unsupported device selectors"""
    pass


@_SKIP
def test_ios_should_work_with_partial_options():
    """should work with partial options"""
    pass


@_SKIP
def test_should_allow_documented_ios_device_override_option_name():
    """should allow documented iOS device override option name"""
    pass


@_SKIP
def test_ios_device_input_opt_should_include_keyboard_options():
    """IOSDeviceInputOpt should include keyboard options"""
    pass


@_SKIP
def test_should_include_all_required_harmonyos_device_options():
    """should include all required HarmonyOS device options"""
    pass


@_SKIP
def test_harmony_device_input_opt_should_include_keyboard_options():
    """HarmonyDeviceInputOpt should include keyboard options"""
    pass


@_SKIP
def test_midscene_yaml_script_android_env_should_include_all_android_device_opt_except_custom_actions():
    """MidsceneYamlScriptAndroidEnv should include all AndroidDeviceOpt except customActions"""
    pass


@_SKIP
def test_midscene_yaml_script_ios_env_should_include_all_ios_device_opt_except_custom_actions():
    """MidsceneYamlScriptIOSEnv should include all IOSDeviceOpt except customActions"""
    pass


@_SKIP
def test_should_work_with_minimal_yaml_config():
    """should work with minimal YAML config"""
    pass


@_SKIP
def test_android_device_opt_should_be_assignable_to_agent_function_parameter():
    """AndroidDeviceOpt should be assignable to agent function parameter"""
    pass


@_SKIP
def test_ios_device_opt_should_be_assignable_to_agent_function_parameter():
    """IOSDeviceOpt should be assignable to agent function parameter"""
    pass


@_SKIP
def test_yaml_config_should_be_compatible_with_device_options():
    """YAML config should be compatible with device options"""
    pass


@_SKIP
def test_should_only_accept_valid_ime_strategy_values():
    """should only accept valid imeStrategy values"""
    pass


@_SKIP
def test_should_only_accept_valid_keyboard_dismiss_strategy_values():
    """should only accept valid keyboardDismissStrategy values"""
    pass


@_SKIP
def test_should_only_accept_valid_screenshot_strategy_values():
    """should only accept valid screenshotStrategy values"""
    pass


@_SKIP
def test_should_reject_invalid_screenshot_strategy_values():
    """should reject invalid screenshotStrategy values"""
    pass
