"""Tests for the ported shared CLI framework and agent-tool helpers."""

import json
import sys

import pytest

from midscene.core.skill import run_skill_cli
from midscene.core.types import InterfaceType

from midscene.shared.agent_tools.error_formatter import get_error_message
from midscene.shared.agent_tools.init_arg_utils import (
    extract_namespaced_args,
    sanitize_namespaced_args,
)
from midscene.shared.agent_tools.observation_record import (
    parse_ui_observation_record,
    write_ui_observation_record,
)
from midscene.shared.agent_tools.tool_defaults import strip_behavior_flags
from midscene.shared.agent_tools.types import ToolDefinition, ToolResult, schema_field
from midscene.shared.agent_tools.user_prompt import compose_user_prompt
from midscene.shared.agent_tools.base_tools import InitArgSpec, BaseMidsceneTools
from midscene.shared.cli.cli_args import (
    canonicalize_cli_arg_keys,
    format_cli_validation_error,
    parse_cli_args,
)
from midscene.shared.cli.cli_error import CLIError
from midscene.shared.cli.cli_runner import run_tools_cli
from midscene.shared.cli.cli_value import parse_cli_value, parse_value
from midscene.shared.cli.verbose import (
    emit_cli_verbose_event,
    strip_verbose_flag,
    with_cli_verbose_context,
)
from midscene.shared.key_alias_utils import (
    camel_to_kebab,
    get_key_aliases,
    kebab_to_camel,
)


def _noop_handler(args):
    async def handler(_args):
        return ToolResult([{"type": "text", "text": "ok"}])

    return handler


def _definition(schema, cli=None, name="act"):
    return ToolDefinition(
        name=name,
        description="test command",
        schema=schema,
        handler=_noop_handler(schema),
        cli=cli,
    )


def test_key_aliases():
    assert kebab_to_camel("image-name") == "imageName"
    assert camel_to_kebab("imageName") == "image-name"
    assert get_key_aliases("imageName") == ["imageName", "image-name"]


def test_parse_value():
    assert parse_value("12") == 12
    assert parse_value("1.5") == 1.5
    assert parse_value('{"a": 1}') == {"a": 1}
    assert parse_value("hello") == "hello"


def test_parse_cli_value_respects_schema():
    assert parse_cli_value("12", {"type": "number"}) == 12
    assert parse_cli_value("12", {"type": "string"}) == "12"
    assert parse_cli_value("true", {"type": "boolean"}) is True
    assert parse_cli_value('{"a": 1}', {"type": "object"}) == {"a": 1}


def test_parse_cli_args_and_aliases():
    definition = _definition(
        {"imageName": schema_field("string")},
        cli={
            "options": {
                "imageName": {
                    "preferredName": "image-name",
                    "aliases": ["imageName"],
                }
            }
        },
    )
    parsed = parse_cli_args(["--image-name", "a"], definition)
    assert parsed == {"image-name": "a"}
    canonical = canonicalize_cli_arg_keys("midscene", "act", definition, parsed)
    assert canonical == {"imageName": "a"}

    with pytest.raises(CLIError):
        canonicalize_cli_arg_keys(
            "midscene",
            "act",
            definition,
            {"image-name": "a", "imageName": "b"},
        )


def test_parse_cli_args_repeated_values():
    definition = _definition({"image": schema_field("string | string[]", optional=True)})
    parsed = parse_cli_args(["--image", "a", "--image", "b"], definition)
    assert parsed == {"image": ["a", "b"]}


def test_format_cli_validation_error_unknown_and_required():
    definition = _definition({"prompt": schema_field("string")})
    assert "Unknown option" in format_cli_validation_error(
        "midscene", "act", definition, {"nope": "x"}
    )
    assert "Required" in format_cli_validation_error(
        "midscene", "act", definition, {}
    )
    assert "Expected string" in format_cli_validation_error(
        "midscene", "act", definition, {"prompt": 1}
    )
    assert (
        format_cli_validation_error("midscene", "act", definition, {"prompt": "x"})
        is None
    )


def test_disallowed_option_spelling():
    definition = _definition(
        {"imageName": schema_field("string")},
        cli={"options": {"imageName": {"preferredName": "image-name"}}},
    )
    message = format_cli_validation_error(
        "midscene", "act", definition, {"imageName": "x"}
    )
    assert message is not None
    assert "Unsupported option" in message


def test_strip_verbose_and_behavior_flags():
    stripped = strip_verbose_flag(["--verbose=jsonl", "act", "--deep-locate"])
    assert stripped == {
        "rawArgs": ["act", "--deep-locate"],
        "verbose": True,
        "format": "jsonl",
    }
    raw, defaults = strip_behavior_flags(stripped["rawArgs"])
    assert raw == ["act"]
    assert defaults == {"locate": {"deepLocate": True}, "act": {"deepLocate": True}}


def test_compose_user_prompt():
    assert compose_user_prompt("hello") == "hello"
    assert compose_user_prompt("hello", image=["a"], image_name=["x"]) == {
        "prompt": "hello",
        "images": [{"name": "x", "url": "a"}],
    }
    with pytest.raises(ValueError):
        compose_user_prompt("hello", image=["a"], image_name=[])


def test_init_arg_utils():
    args = {"android": {"deviceId": "d1"}, "android.timeout": 5, "other": 1}
    extracted = extract_namespaced_args(args, "android", ["deviceId", "timeout"])
    assert extracted == {"deviceId": "d1", "timeout": 5}
    sanitized = sanitize_namespaced_args(
        args, "android", ["deviceId", "timeout"]
    )
    assert sanitized == {"other": 1}


def test_error_message_for_exception():
    assert get_error_message(RuntimeError("boom")) == "boom"


def test_observation_record_roundtrip(tmp_path):
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"image")
    record = {
        "type": "midscene_ui_observation",
        "version": 1,
        "startedAt": 1,
        "endedAt": 2,
        "frames": [
            {"path": str(frame), "mimeType": "image/png", "capturedAt": 1}
        ],
        "shotSize": {"width": 100, "height": 50},
        "shrunkShotToLogicalRatio": 1.0,
    }
    output = write_ui_observation_record(record, str(tmp_path / "out.json"))
    manifest = json.loads((tmp_path / "out.json").read_text())
    assert manifest["frames"][0]["path"].startswith("out.frames/")
    assert (tmp_path / "out.frames").is_dir()
    assert output == str(tmp_path / "out.json")
    assert parse_ui_observation_record(manifest)["frames"][0]["mimeType"] == "image/png"


@pytest.mark.asyncio
async def test_run_tools_cli_dispatches_and_destroys(capsys):
    calls = []

    async def handler(args):
        calls.append(args)
        return ToolResult([{"type": "text", "text": f"acted:{args['prompt']}"}])

    class FakeTools:
        def __init__(self):
            self.destroyed = False
            self.defaults = {}

        async def init_tools(self):
            return None

        def get_tool_definitions(self):
            return [
                ToolDefinition(
                    name="midscene_act",
                    description="Run an action",
                    schema={"prompt": schema_field("string")},
                    handler=handler,
                    cli={"positionals": ["prompt"]},
                )
            ]

        def get_cli_tool_definitions(self):
            return []

        def set_tool_defaults(self, defaults):
            self.defaults = defaults

        async def destroy(self):
            self.destroyed = True

    tools = FakeTools()
    await run_tools_cli(
        tools,
        "midscene-test",
        {"stripPrefix": "midscene_", "argv": ["act", "open the page"]},
    )
    assert calls == [{"prompt": "open the page"}]
    assert tools.destroyed is True
    assert "acted:open the page" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_tools_cli_unknown_command(capsys):
    class FakeTools:
        async def init_tools(self):
            return None

        def get_tool_definitions(self):
            return [_definition({"prompt": schema_field("string")})]

        async def destroy(self):
            return None

    with pytest.raises(CLIError):
        await run_tools_cli(FakeTools(), "midscene-test", {"argv": ["nope"]})
    assert "Unknown command: nope" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_verbose_emission(capsys):
    async def run():
        emit_cli_verbose_event({"event": "command_start", "args": {"prompt": "go"}})

    await with_cli_verbose_context(
        {
            "enabled": True,
            "format": "text",
            "scriptName": "s",
            "commandName": "assert",
        },
        run,
    )
    assert "[Midscene] assert started" in capsys.readouterr().out


class _FakeInitTools(BaseMidsceneTools):
    def __init__(self):
        super().__init__()
        self.init_arg_spec = InitArgSpec(
            namespace="android",
            shape={"deviceId": schema_field("string")},
        )
        self.created = 0

    def create_temporary_device(self):
        self.created += 1

        class Device:
            interface_type = "web"

        return Device()

    async def ensure_agent(self, init_param=None):
        return object()


@pytest.mark.asyncio
async def test_base_tools_init_arg_metadata_and_tools():
    tools = _FakeInitTools()
    schema = tools.get_agent_init_arg_schema()
    assert list(schema) == ["android.deviceId"]
    assert tools.extract_agent_init_param({"android.deviceId": "d1"}) == {
        "deviceId": "d1"
    }
    assert tools.sanitize_tool_args(
        {"android.deviceId": "d1", "prompt": "x"}
    ) == {"prompt": "x"}
    metadata = tools.get_agent_init_arg_cli_metadata()
    assert metadata is None

    await tools.init_tools()
    assert tools.created == 1
    names = {definition.name for definition in tools.get_tool_definitions()}
    assert {"take_screenshot", "act", "assert"} <= names
    assert all(
        "android.deviceId" in definition.schema
        for definition in tools.get_tool_definitions()
        if definition.name in ("act", "assert")
    )


class _SkillDevice:
    interface_type = InterfaceType.WEB


@pytest.mark.asyncio
async def test_run_skill_cli_prints_help(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["prog", "--help"])
    await run_skill_cli({"DeviceClass": _SkillDevice, "scriptName": "my-device"})
    out = capsys.readouterr().out
    assert "Usage: my-device <command>" in out
    assert "act" in out
    assert "assert" in out
    assert "record" in out


@pytest.mark.asyncio
async def test_run_skill_cli_reports_unknown_command(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["prog", "nope"])
    with pytest.raises(SystemExit) as error:
        await run_skill_cli(
            {"DeviceClass": _SkillDevice, "scriptName": "my-device"}
        )
    assert error.value.code == 1
    assert "Unknown command: nope" in capsys.readouterr().err
