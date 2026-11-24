"""Port of upstream packages/cli/tests/unit-test/config-factory.test.ts."""

import os
import re

import pytest

from midscene.cli import config_factory


def _write_config(tmp_path, content: str) -> str:
    path = tmp_path / "index.yml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _sequence(values):
    iterator = iter(values)

    def fake_match(_pattern, _options=None):
        return next(iterator)

    return fake_match


@pytest.mark.asyncio
async def test_should_parse_valid_config_yaml_with_all_options(tmp_path, monkeypatch):
    """should parse valid config YAML with all options."""
    content = """
files:
  - "*.yml"
concurrent: 3
continueOnError: true
headed: true
keepWindow: true
dotenvOverride: true
dotenvDebug: false
web:
  url: "http://example.com"
  userAgent: "yaml-ua"
android:
  deviceId: "yaml-device"
harmony:
  deviceId: "yaml-harmony-device"
summary: "yaml-summary.json"
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["file1.yml"])

    result = await config_factory.parse_config_yaml(path)

    assert result == {
        "concurrent": 3,
        "continueOnError": True,
        "retry": 0,
        "headed": True,
        "keepWindow": True,
        "dotenvOverride": True,
        "dotenvDebug": False,
        "web": {"url": "http://example.com", "userAgent": "yaml-ua"},
        "android": {"deviceId": "yaml-device"},
        "harmony": {"deviceId": "yaml-harmony-device"},
        "summary": "yaml-summary.json",
        "patterns": ["*.yml"],
        "shareBrowserContext": False,
        "reusePage": False,
        "files": ["file1.yml"],
        "setup": None,
    }


@pytest.mark.asyncio
async def test_should_use_default_values_when_options_are_not_specified(
    tmp_path, monkeypatch
):
    """should use default values when options are not specified."""
    path = _write_config(tmp_path, 'files: ["*.yml"]')
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["test.yml"])

    result = await config_factory.parse_config_yaml(path)

    assert result["concurrent"] == 1
    assert result["continueOnError"] is False
    assert result["retry"] == 0
    assert result["headed"] is False
    assert result["keepWindow"] is False
    assert result["dotenvOverride"] is False
    assert result["dotenvDebug"] is False
    assert re.search(r"index-\d+\.json$", result["summary"])


@pytest.mark.asyncio
async def test_should_parse_the_retry_option_from_the_config_yaml(
    tmp_path, monkeypatch
):
    """should parse the retry option from the config YAML."""
    path = _write_config(tmp_path, 'files: ["*.yml"]\nretry: 2')
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["test.yml"])

    result = await config_factory.parse_config_yaml(path)

    assert result["retry"] == 2


@pytest.mark.asyncio
async def test_should_throw_an_error_if_files_is_not_an_array(tmp_path):
    """should throw an error if "files" is not an array."""
    path = _write_config(tmp_path, 'files: "not-an-array"')

    with pytest.raises(ValueError, match='Config YAML must contain a "files" array'):
        await config_factory.parse_config_yaml(path)


@pytest.mark.asyncio
async def test_should_throw_an_error_if_no_files_are_found(tmp_path, monkeypatch):
    """should throw an error if no files are found."""
    path = _write_config(tmp_path, 'files: ["*.yml"]')
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: [])

    with pytest.raises(
        ValueError,
        match='No YAML files found matching the patterns in "files"',
    ):
        await config_factory.parse_config_yaml(path)


@pytest.mark.asyncio
async def test_should_resolve_the_setup_file_ahead_of_the_main_files(
    tmp_path, monkeypatch
):
    """should resolve the setup file ahead of the main files."""
    content = """
setup: "login.yml"
files:
  - "*.yml"
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["login.yml"]]),
    )

    result = await config_factory.parse_config_yaml(path)

    assert result["files"] == ["search.yml"]
    assert result["setup"] == "login.yml"


@pytest.mark.asyncio
async def test_should_leave_setup_undefined_when_absent(tmp_path, monkeypatch):
    """should leave setup undefined when absent."""
    path = _write_config(tmp_path, 'files: ["*.yml"]')
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["test.yml"])

    result = await config_factory.parse_config_yaml(path)

    assert result["setup"] is None


@pytest.mark.asyncio
async def test_should_throw_when_the_setup_pattern_matches_nothing(
    tmp_path, monkeypatch
):
    """should throw when the setup pattern matches nothing."""
    content = """
setup: "login.yml"
files:
  - "*.yml"
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], []]),
    )

    with pytest.raises(ValueError, match='No YAML file found matching "setup"'):
        await config_factory.parse_config_yaml(path)


@pytest.mark.asyncio
async def test_should_throw_when_the_setup_pattern_matches_multiple_files(
    tmp_path, monkeypatch
):
    """should throw when the setup pattern matches multiple files."""
    content = """
setup: "setup-*.yml"
files:
  - "*.yml"
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["setup-a.yml", "setup-b.yml"]]),
    )

    with pytest.raises(ValueError, match="must reference a single YAML file"):
        await config_factory.parse_config_yaml(path)


@pytest.mark.asyncio
async def test_should_preserve_duplicate_file_entries(tmp_path, monkeypatch):
    """should preserve duplicate file entries."""
    content = """
files:
  - "login.yml"
  - "test.yml"
  - "login.yml"
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["login.yml"], ["test.yml"], ["login.yml"]]),
    )

    result = await config_factory.parse_config_yaml(path)

    assert result["files"] == ["login.yml", "test.yml", "login.yml"]
    assert len(result["files"]) == 3


@pytest.mark.asyncio
async def test_should_automatically_enable_headed_when_keep_window_is_true(
    tmp_path, monkeypatch
):
    """should automatically enable headed when keepWindow is true."""
    content = """
files:
  - file1.yml
keepWindow: true
headed: false
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["file1.yml"])

    result1 = await config_factory.create_config(path)
    assert result1["keepWindow"] is True
    assert result1["headed"] is True

    result2 = await config_factory.create_config(
        path, {"keepWindow": True, "headed": False}
    )
    assert result2["keepWindow"] is True
    assert result2["headed"] is True

    result3 = await config_factory.create_config(
        path, {"keepWindow": False, "headed": True}
    )
    assert result3["keepWindow"] is False
    assert result3["headed"] is True


@pytest.mark.asyncio
async def test_should_merge_command_line_options_over_config_file_options(
    tmp_path, monkeypatch
):
    """should merge command-line options over config file options."""
    content = """
files:
  - file1.yml
concurrent: 2
web:
  userAgent: "from-file"
  viewportWidth: 800
android:
  deviceId: "from-file"
harmony:
  deviceId: "harmony-from-file"
  launch: "file.bundle"
  autoDismissKeyboard: false
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["file1.yml"])

    cmd_line_options = {
        "concurrent": 5,
        "headed": True,
        "summary": "from-cmd.json",
        "web": {"userAgent": "from-cmd", "viewportHeight": 900},
        "android": {"deviceId": "from-cmd"},
        "harmony": {
            "deviceId": "harmony-from-cmd",
            "autoDismissKeyboard": True,
        },
    }

    result = await config_factory.create_config(path, cmd_line_options)

    assert result["concurrent"] == 5
    assert result["headed"] is True
    assert result["summary"] == "from-cmd.json"
    assert result["globalConfig"] == {
        "web": {
            "userAgent": "from-cmd",
            "viewportWidth": 800,
            "viewportHeight": 900,
        },
        "android": {"deviceId": "from-cmd"},
        "harmony": {
            "deviceId": "harmony-from-cmd",
            "launch": "file.bundle",
            "autoDismissKeyboard": True,
        },
    }
    assert result["globalConfig"]["harmony"] == {
        "deviceId": "harmony-from-cmd",
        "launch": "file.bundle",
        "autoDismissKeyboard": True,
    }


@pytest.mark.asyncio
async def test_should_keep_setup_when_share_browser_context_is_enabled(
    tmp_path, monkeypatch
):
    """should keep setup when shareBrowserContext is enabled."""
    content = """
setup: login.yml
files:
  - search.yml
shareBrowserContext: true
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["login.yml"]]),
    )

    result = await config_factory.create_config(path)

    assert result["shareBrowserContext"] is True
    assert result["setup"] == "login.yml"
    assert result["files"] == ["search.yml"]


@pytest.mark.asyncio
async def test_should_keep_setup_without_deciding_target_specific_sharing(
    tmp_path, monkeypatch
):
    """should keep setup without deciding target-specific sharing."""
    content = """
setup: login.yml
files:
  - search.yml
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["login.yml"]]),
    )

    result = await config_factory.create_config(path)

    assert result["setup"] == "login.yml"
    assert result["files"] == ["search.yml"]
    assert result["shareBrowserContext"] is False


@pytest.mark.asyncio
async def test_should_override_config_files_with_command_line_files_parameter(
    tmp_path, monkeypatch
):
    """should override config files with command-line files parameter."""
    content = """
files:
  - config-file1.yml
  - config-file2.yml
concurrent: 2
"""
    path = _write_config(tmp_path, content)
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["config-file1.yml"], ["config-file2.yml"], ["cmd-file.yml"]]),
    )

    result = await config_factory.create_config(path, {"files": ["cmd-file.yml"]})

    assert result["files"] == ["cmd-file.yml"]
    assert result["concurrent"] == 2


@pytest.mark.asyncio
async def test_create_files_config_enables_headed_when_keep_window_is_true(
    monkeypatch,
):
    """should automatically enable headed when keepWindow is true."""
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["test.yml"])

    result1 = await config_factory.create_files_config(
        ["test.yml"], {"keepWindow": True, "headed": False}
    )
    assert result1["keepWindow"] is True
    assert result1["headed"] is True

    result2 = await config_factory.create_files_config(
        ["test.yml"], {"keepWindow": True}
    )
    assert result2["keepWindow"] is True
    assert result2["headed"] is True

    result3 = await config_factory.create_files_config(
        ["test.yml"], {"keepWindow": False, "headed": True}
    )
    assert result3["keepWindow"] is False
    assert result3["headed"] is True

    result4 = await config_factory.create_files_config(
        ["test.yml"], {"keepWindow": False, "headed": False}
    )
    assert result4["keepWindow"] is False
    assert result4["headed"] is False


@pytest.mark.asyncio
async def test_should_create_config_with_default_options_and_expand_patterns(
    monkeypatch,
):
    """should create config with default options and expand patterns."""
    patterns = ["test1.yml", "test*.yml"]
    calls = []
    values = iter(
        [
            ["test1.yml"],
            ["test1.yml", "testA.yml", "testB.yml"],
        ]
    )

    def fake_match(pattern, options=None):
        calls.append((pattern, options))
        return next(values)

    monkeypatch.setattr(config_factory, "match_yaml_files", fake_match)

    result = await config_factory.create_files_config(patterns)

    assert re.search(r"summary-\d+\.json$", result["summary"])
    assert {**result, "summary": "<summary>"} == {
        "files": ["test1.yml", "test1.yml", "testA.yml", "testB.yml"],
        "setup": None,
        "concurrent": 1,
        "continueOnError": False,
        "retry": 0,
        "shareBrowserContext": False,
        "reusePage": False,
        "summary": "<summary>",
        "headed": False,
        "keepWindow": False,
        "dotenvOverride": False,
        "dotenvDebug": False,
        "globalConfig": {},
    }
    assert (patterns[0], {"cwd": os.getcwd()}) in calls
    assert (patterns[1], {"cwd": os.getcwd()}) in calls


@pytest.mark.asyncio
async def test_should_resolve_setup_when_share_browser_context_is_enabled(
    monkeypatch,
):
    """should resolve setup when shareBrowserContext is enabled."""
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["login.yml"]]),
    )

    result = await config_factory.create_files_config(
        ["search.yml"],
        {"shareBrowserContext": True, "setup": "login.yml"},
    )

    assert result["setup"] == "login.yml"
    assert result["files"] == ["search.yml"]


@pytest.mark.asyncio
async def test_should_resolve_setup_without_deciding_target_specific_sharing(
    monkeypatch,
):
    """should resolve setup without deciding target-specific sharing."""
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([["search.yml"], ["login.yml"]]),
    )

    result = await config_factory.create_files_config(
        ["search.yml"], {"setup": "login.yml"}
    )

    assert result["setup"] == "login.yml"
    assert result["files"] == ["search.yml"]
    assert result["shareBrowserContext"] is False


@pytest.mark.asyncio
async def test_should_forward_the_retry_option_through_create_files_config(
    monkeypatch,
):
    """should forward the retry option through createFilesConfig."""
    monkeypatch.setattr(config_factory, "match_yaml_files", lambda *_: ["file1.yml"])

    result = await config_factory.create_files_config(["*.yml"], {"retry": 3})

    assert result["retry"] == 3


@pytest.mark.asyncio
async def test_should_create_config_with_all_custom_options_and_expand_patterns(
    monkeypatch,
):
    """should create config with all custom options and expand patterns."""
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        lambda *_: ["file1.yml", "file2.yml"],
    )

    options = {
        "concurrent": 3,
        "continueOnError": True,
        "summary": "custom.json",
        "shareBrowserContext": True,
        "reusePage": False,
        "headed": True,
        "keepWindow": True,
        "dotenvOverride": True,
        "dotenvDebug": False,
        "web": {"userAgent": "custom-ua"},
        "android": {"deviceId": "custom-device"},
        "harmony": {"deviceId": "custom-harmony-device"},
        "computer": {"displayId": "main"},
        "interface": {"module": "./custom-interface.js"},
    }
    result = await config_factory.create_files_config(["*.yml"], options)

    assert result == {
        "files": ["file1.yml", "file2.yml"],
        "setup": None,
        "concurrent": 3,
        "continueOnError": True,
        "retry": 0,
        "summary": "custom.json",
        "shareBrowserContext": True,
        "reusePage": False,
        "headed": True,
        "keepWindow": True,
        "dotenvOverride": True,
        "dotenvDebug": False,
        "globalConfig": {
            "web": {"userAgent": "custom-ua"},
            "android": {"deviceId": "custom-device"},
            "harmony": {"deviceId": "custom-harmony-device"},
            "computer": {"displayId": "main"},
            "interface": {"module": "./custom-interface.js"},
        },
    }


@pytest.mark.asyncio
async def test_should_create_config_for_the_documented_yaml_runner_config_file_example(
    monkeypatch,
):
    """should create config for the documented YAML runner config-file example."""
    patterns = [
        "./scripts/search-iphone.yaml",
        "./scripts/search-laptop.yaml",
        "./scripts/search-headphones.yaml",
        "./scripts/search-camera.yaml",
    ]
    monkeypatch.setattr(
        config_factory,
        "match_yaml_files",
        _sequence([[pattern] for pattern in patterns]),
    )

    result = await config_factory.create_files_config(
        patterns,
        {
            "concurrent": 4,
            "continueOnError": True,
            "shareBrowserContext": True,
            "summary": "doc-summary.json",
            "web": {
                "userAgent": "Doc Agent",
                "viewportWidth": 1440,
                "viewportHeight": 900,
            },
            "android": {
                "deviceId": "android-doc-device",
            },
            "ios": {
                "wdaPort": 8100,
                "wdaHost": "127.0.0.1",
            },
        },
    )

    assert result == {
        "files": patterns,
        "setup": None,
        "concurrent": 4,
        "continueOnError": True,
        "retry": 0,
        "shareBrowserContext": True,
        "reusePage": False,
        "summary": "doc-summary.json",
        "headed": False,
        "keepWindow": False,
        "dotenvOverride": False,
        "dotenvDebug": False,
        "globalConfig": {
            "web": {
                "userAgent": "Doc Agent",
                "viewportWidth": 1440,
                "viewportHeight": 900,
            },
            "android": {
                "deviceId": "android-doc-device",
            },
            "ios": {
                "wdaPort": 8100,
                "wdaHost": "127.0.0.1",
            },
        },
    }
