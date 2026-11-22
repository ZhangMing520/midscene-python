"""CLI runner and argument parsing (upstream cli-runner.test.ts)."""

import json
import re
from pathlib import Path

import pytest

from midscene.shared.agent_tools.types import ToolDefinition, ToolResult
from midscene.shared.cli.cli_args import parse_cli_args, parse_value
from midscene.shared.cli.cli_error import CLIError, report_cli_error
from midscene.shared.cli.cli_runner import remove_prefix, run_tools_cli


async def _noop_handler(_args):
    return ToolResult([{"type": "text", "text": "ok"}])


def _tool(name, handler=None, schema=None, cli=None, description=None):
    return ToolDefinition(
        name=name,
        description=description or f"{name} command",
        schema=schema or {},
        handler=handler or _noop_handler,
        cli=cli,
    )


class _FakeTools:
    def __init__(self, definitions, cli_definitions=None):
        self._definitions = definitions
        self._cli_definitions = cli_definitions or []
        self.destroyed = 0
        self.defaults = None

    async def init_tools(self):
        return None

    def get_tool_definitions(self):
        return self._definitions

    def get_cli_tool_definitions(self):
        return self._cli_definitions

    def set_tool_defaults(self, defaults):
        self.defaults = defaults

    async def destroy(self):
        self.destroyed += 1


class TestParseValue:
    def test_parses_json_objects(self):
        assert parse_value('{"prompt":"the login button"}') == {
            "prompt": "the login button"
        }

    def test_parses_nested_json_objects(self):
        assert parse_value('{"a":{"b":1}}') == {"a": {"b": 1}}

    def test_parses_json_arrays(self):
        assert parse_value("[1,2,3]") == [1, 2, 3]

    def test_returns_string_for_invalid_json_starting_with_brace(self):
        assert parse_value("{not json}") == "{not json}"

    def test_returns_string_for_invalid_json_starting_with_bracket(self):
        assert parse_value("[broken") == "[broken"

    def test_parses_positive_integers(self):
        assert parse_value("42") == 42

    def test_parses_negative_integers(self):
        assert parse_value("-5") == -5

    def test_parses_decimals(self):
        assert parse_value("3.14") == 3.14

    def test_parses_negative_decimals(self):
        assert parse_value("-2.5") == -2.5

    def test_parses_zero(self):
        assert parse_value("0") == 0

    def test_returns_string_for_non_numeric_text(self):
        assert parse_value("hello") == "hello"

    def test_returns_string_for_partial_numeric_text(self):
        assert parse_value("12abc") == "12abc"

    def test_returns_string_for_empty_string(self):
        assert parse_value("") == ""

    def test_returns_string_for_url(self):
        assert parse_value("https://example.com") == "https://example.com"


class TestParseCliArgs:
    def test_parses_key_value_pairs(self):
        assert parse_cli_args(["--url", "https://example.com"]) == {
            "url": "https://example.com"
        }

    def test_parses_key_equals_value_format(self):
        assert parse_cli_args(["--url=https://example.com"]) == {
            "url": "https://example.com"
        }

    def test_preserves_empty_string_values_in_both_option_formats(self):
        assert parse_cli_args(["--content", ""]) == {"content": ""}
        assert parse_cli_args(["--content="]) == {"content": ""}

    def test_consumes_empty_string_values_before_subsequent_options(self):
        assert parse_cli_args(["--content", "", "--verbose"]) == {
            "content": "",
            "verbose": True,
        }
        assert parse_cli_args(["--content", "", "--content", "text"]) == {
            "content": ["", "text"]
        }

    def test_preserves_empty_string_values_for_string_schema_fields(self):
        defn = _tool("configure", schema={"content": {"type": "string"}})
        assert parse_cli_args(["--content", ""], defn) == {"content": ""}

    def test_parses_boolean_flags(self):
        assert parse_cli_args(["--verbose"]) == {"verbose": True}

    def test_parses_consecutive_boolean_flags(self):
        assert parse_cli_args(["--verbose", "--debug"]) == {
            "verbose": True,
            "debug": True,
        }

    def test_parses_json_values(self):
        assert parse_cli_args(["--locate", '{"prompt":"the login button"}']) == {
            "locate": {"prompt": "the login button"}
        }

    def test_parses_numeric_values(self):
        assert parse_cli_args(["--timeout", "30"]) == {"timeout": 30}

    def test_parses_mixed_arguments(self):
        assert parse_cli_args(
            [
                "--url",
                "https://example.com",
                "--timeout",
                "30",
                "--verbose",
                "--locate",
                '{"prompt":"button"}',
            ]
        ) == {
            "url": "https://example.com",
            "timeout": 30,
            "verbose": True,
            "locate": {"prompt": "button"},
        }

    def test_ignores_non_dashed_arguments(self):
        assert parse_cli_args(["positional", "--key", "value"]) == {"key": "value"}

    def test_returns_empty_object_for_empty_args(self):
        assert parse_cli_args([]) == {}

    def test_handles_key_equals_value_with_json(self):
        assert parse_cli_args(['--locate={"prompt":"btn"}']) == {
            "locate": {"prompt": "btn"}
        }

    def test_handles_key_equals_value_with_number(self):
        assert parse_cli_args(["--timeout=30"]) == {"timeout": 30}

    def test_treats_trailing_flag_as_boolean(self):
        assert parse_cli_args(["--key", "value", "--flag"]) == {
            "key": "value",
            "flag": True,
        }

    def test_handles_direction_style_string_values(self):
        assert parse_cli_args(["--direction", "down"]) == {"direction": "down"}

    def test_handles_content_with_spaces_in_value(self):
        assert parse_cli_args(["--content", "hello world"]) == {
            "content": "hello world"
        }

    def test_preserves_dotted_keys_as_flat_args(self):
        assert parse_cli_args(
            [
                "--android.deviceId",
                "127.0.0.1:7555",
                "--ios.wda-port",
                "8100",
            ]
        ) == {
            "android.deviceId": "127.0.0.1:7555",
            "ios.wda-port": 8100,
        }

    def test_treats_namespace_like_keys_as_independent_flat_args(self):
        assert parse_cli_args(["--android", "foo", "--android.deviceId", "bar"]) == {
            "android": "foo",
            "android.deviceId": "bar",
        }

    def test_accumulates_repeated_flags_into_arrays(self):
        assert parse_cli_args(
            [
                "--image",
                "./a.png",
                "--image",
                "./b.png",
                "--image-name",
                "a",
                "--image-name",
                "b",
            ]
        ) == {
            "image": ["./a.png", "./b.png"],
            "image-name": ["a", "b"],
        }

    def test_preserves_dotted_kebab_case_keys_as_flat_args(self):
        assert parse_cli_args(["--android.device-id", "127.0.0.1:7555"]) == {
            "android.device-id": "127.0.0.1:7555"
        }

    def test_preserves_numeric_looking_values_for_string_compatible_fields(self):
        defn = _tool(
            "connect",
            schema={
                "deviceId": {"type": "string"},
                "mode": {"type": "enum", "enum": ["123", "safe"]},
                "literal": {"type": "literal", "value": "007"},
                "stringOrNumber": {"type": "string|number"},
            },
            cli={
                "options": {
                    "deviceId": {"preferredName": "device-id"},
                }
            },
        )

        assert parse_cli_args(
            [
                "--device-id",
                "0009007199254740993",
                "--mode=123",
                "--literal",
                "007",
                "--string-or-number",
                "42",
            ],
            defn,
        ) == {
            "device-id": "0009007199254740993",
            "mode": "123",
            "literal": "007",
            "string-or-number": "42",
        }

    def test_decodes_values_according_to_non_string_schema_fields(self):
        defn = _tool(
            "configure",
            schema={
                "timeout": {"type": "number"},
                "enabled": {"type": "boolean"},
                "attempts": {"type": "literal", "value": 3},
                "payload": {"type": "string|object"},
            },
        )

        assert parse_cli_args(
            [
                "--timeout=-2.5",
                "--enabled=false",
                "--attempts",
                "3",
                "--payload",
                '{"prompt":"go"}',
            ],
            defn,
        ) == {
            "timeout": -2.5,
            "enabled": False,
            "attempts": 3,
            "payload": {"prompt": "go"},
        }

    def test_preserves_json_looking_text_and_repeated_numeric_image_names(self):
        defn = _tool(
            "act",
            schema={
                "prompt": {"type": "string", "optional": True},
                "imageName": {"type": "string|string[]"},
                "payload": {"type": "object"},
            },
        )
        assert parse_cli_args(
            [
                '--prompt={"account":"007"}',
                "--image-name=007",
                "--image-name=9007199254740993",
                '--payload={"prompt":"go"}',
            ],
            defn,
        ) == {
            "prompt": '{"account":"007"}',
            "image-name": ["007", "9007199254740993"],
            "payload": {"prompt": "go"},
        }

    def test_retains_invalid_typed_inputs_for_schema_validation_to_reject(self):
        defn = _tool(
            "configure",
            schema={
                "enabled": {"type": "boolean"},
                "timeout": {"type": "number"},
                "payload": {"type": "object"},
            },
        )
        assert parse_cli_args(
            ["--enabled=maybe", "--timeout=slow", "--payload={broken"], defn
        ) == {
            "enabled": "maybe",
            "timeout": "slow",
            "payload": "{broken",
        }

    def test_decodes_repeated_collection_values_using_their_element_schemas(self):
        defn = _tool(
            "demo",
            schema={
                "values": {"type": "number[]", "optional": True},
                "flags": {"type": "boolean[]"},
                "names": {"type": "string[]"},
            },
        )
        parsed = parse_cli_args(
            [
                "--values=1",
                "--values=2",
                "--flags=true",
                "--flags=false",
                "--names=007",
                "--names=9007199254740993",
            ],
            defn,
        )
        assert parsed == {
            "values": [1, 2],
            "flags": [True, False],
            "names": ["007", "9007199254740993"],
        }

    def test_accumulates_repeated_flags_into_an_array(self):
        assert parse_cli_args(
            [
                "--htmlReport",
                "a.html",
                "--htmlReport",
                "b.html",
                "--htmlReport",
                "c.html",
            ]
        ) == {"htmlReport": ["a.html", "b.html", "c.html"]}

    def test_accumulates_repeated_key_equals_value_into_an_array(self):
        assert parse_cli_args(["--report=a.html", "--report=b.html"]) == {
            "report": ["a.html", "b.html"]
        }

    @pytest.mark.skip(
        reason="Python schema descriptors do not model Zod nativeEnum/intersection/"
        "tuple-rest/constructor identity"
    )
    def test_decodes_native_enum_inputs(self):
        pass

    @pytest.mark.skip(
        reason="Python schema descriptors do not model Zod nativeEnum/intersection/"
        "tuple-rest/constructor identity"
    )
    def test_keeps_numeric_branches_reachable_beside_restricted_strings(self):
        pass

    @pytest.mark.skip(
        reason="Python schema descriptors do not model Zod nativeEnum/intersection/"
        "tuple-rest/constructor identity"
    )
    def test_recognizes_schema_fields_without_constructor_identity(self):
        pass

    @pytest.mark.skip(
        reason="Python schema descriptors do not model Zod nativeEnum/intersection/"
        "tuple-rest/constructor identity"
    )
    def test_preserves_raw_text_for_unsupported_concrete_schemas(self):
        pass

    @pytest.mark.skip(
        reason="Python schema descriptors do not model positional tuple schemas"
    )
    def test_selects_collection_branches_for_repeated_union_inputs_and_tuple_rest_items(
        self,
    ):
        pass


class TestRemovePrefix:
    def test_removes_matching_prefix(self):
        assert remove_prefix("android_connect", "android_") == "connect"

    def test_returns_name_unchanged_when_prefix_does_not_match(self):
        assert remove_prefix("Tap", "android_") == "Tap"

    def test_returns_name_unchanged_when_no_prefix_provided(self):
        assert remove_prefix("android_connect") == "android_connect"

    def test_returns_name_unchanged_when_prefix_is_empty_string(self):
        assert remove_prefix("connect", "") == "connect"

    def test_handles_take_screenshot_without_platform_prefix(self):
        assert remove_prefix("take_screenshot", "android_") == "take_screenshot"


class TestCLIError:
    def test_has_default_exit_code_of_1(self):
        error = CLIError("test")
        assert str(error) == "test"
        assert error.exit_code == 1

    def test_accepts_custom_exit_code(self):
        assert CLIError("test", 2).exit_code == 2

    def test_is_instance_of_exception(self):
        assert isinstance(CLIError("test"), Exception)


class TestReportCLIError:
    def test_prints_cli_error_messages_and_returns_their_exit_code(self):
        logged = []

        assert report_cli_error(CLIError("bad args", 2), logged.append) == 2
        assert logged == ["bad args"]

    def test_prints_non_cli_errors_and_returns_exit_code_1(self):
        logged = []
        error = RuntimeError("boom")

        assert report_cli_error(error, logged.append) == 1
        assert logged == [error]


class TestRunToolsCLI:
    @pytest.mark.asyncio
    async def test_prints_help_when_no_command_given(self, capsys):
        tools = _FakeTools([])
        await run_tools_cli(tools, "test-cli", {"argv": []})
        assert "Usage: test-cli <command> [options]" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_prints_help_for_help_flag(self, capsys):
        tools = _FakeTools([])
        await run_tools_cli(tools, "test-cli", {"argv": ["--help"], "version": "1.2.3"})
        assert "Usage: test-cli <command> [options]" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_prints_version_for_version_flag(self, capsys):
        tools = _FakeTools([])
        await run_tools_cli(
            tools, "test-cli", {"argv": ["--version"], "version": "1.2.3"}
        )
        assert capsys.readouterr().out.strip() == "test-cli v1.2.3"

    @pytest.mark.asyncio
    async def test_prints_version_for_version_command(self, capsys):
        tools = _FakeTools([])
        await run_tools_cli(
            tools, "test-cli", {"argv": ["version"], "version": "1.2.3"}
        )
        assert capsys.readouterr().out.strip() == "test-cli v1.2.3"

    @pytest.mark.asyncio
    async def test_strips_a_global_deep_locate_flag_and_applies_deep_locate_defaults(
        self,
    ):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("tap", handler=handler)])
        await run_tools_cli(
            tools, "test-cli", {"argv": ["--deep-locate", "tap", "--locate", "btn"]}
        )

        assert tools.defaults == {
            "locate": {"deepLocate": True},
            "act": {"deepLocate": True},
        }
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_strips_deep_locate_even_when_it_follows_the_command(self):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("tap", handler=handler)])
        await run_tools_cli(
            tools, "test-cli", {"argv": ["tap", "--deep-locate", "--locate", "btn"]}
        )

        assert tools.defaults == {
            "locate": {"deepLocate": True},
            "act": {"deepLocate": True},
        }
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_does_not_set_tool_defaults_without_a_behavior_flag(self):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("tap", handler=handler)])
        await run_tools_cli(tools, "test-cli", {"argv": ["tap", "--locate", "btn"]})

        assert tools.defaults is None
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_writes_image_tool_results_with_an_extension_matching_the_mime_type(
        self, capsys
    ):
        async def handler(_args):
            return ToolResult(
                [{"type": "image", "data": "aGVsbG8=", "mimeType": "image/jpeg"}]
            )

        tools = _FakeTools([_tool("take_screenshot", handler=handler)])
        await run_tools_cli(tools, "test-cli", {"argv": ["take_screenshot"]})

        message = next(
            line
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("Screenshot saved: ")
        )
        assert re.match(r"^Screenshot saved: .+screenshot-\d+\.jpeg$", message)
        screenshot_path = message.replace("Screenshot saved: ", "")
        assert Path(screenshot_path).exists()
        assert Path(screenshot_path).read_text(encoding="utf-8") == "hello"

    @pytest.mark.asyncio
    async def test_strips_a_global_deep_think_flag_and_applies_act_defaults(self):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("act", handler=handler)])
        await run_tools_cli(
            tools,
            "test-cli",
            {"argv": ["--deep-think", "act", "--prompt", "open settings"]},
        )

        assert tools.defaults == {"act": {"deepThink": True}}
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_merges_defaults_when_both_flags_are_present(self):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("act", handler=handler)])
        await run_tools_cli(
            tools,
            "test-cli",
            {"argv": ["act", "--deep-locate", "--deep-think", "--prompt", "go"]},
        )

        assert tools.defaults == {
            "locate": {"deepLocate": True},
            "act": {"deepLocate": True, "deepThink": True},
        }
        assert len(calls) == 1

    @pytest.mark.skip(reason="Python has no snapshot fixture for the help text")
    def test_help_output_matches_snapshot(self):
        pass

    @pytest.mark.skip(reason="Python has no snapshot fixture for the help text")
    def test_command_help_output_matches_snapshot(self):
        pass

    @pytest.mark.asyncio
    async def test_prefers_cli_display_metadata_for_command_help_output(self, capsys):
        tools = _FakeTools(
            [
                _tool(
                    "android_connect",
                    description="Connect to Android device",
                    schema={
                        "android.deviceId": {
                            "description": "Android device ID (from adb devices)"
                        }
                    },
                    cli={
                        "options": {
                            "android.deviceId": {
                                "preferredName": "device-id",
                                "aliases": ["deviceId"],
                            }
                        }
                    },
                )
            ]
        )

        await run_tools_cli(
            tools,
            "midscene-android",
            {"stripPrefix": "android_", "argv": ["connect", "--help"]},
        )

        output = capsys.readouterr().out
        assert "--device-id" in output
        assert "(aliases: --deviceId)" in output
        assert "--android.device-id" not in output

    @pytest.mark.asyncio
    async def test_rejects_disallowed_dotted_init_arg_spellings_via_cli_schema(self):
        tools = _FakeTools(
            [
                _tool(
                    "android_connect",
                    description="Connect to Android device",
                    schema={
                        "android.deviceId": {
                            "description": "Android device ID (from adb devices)"
                        }
                    },
                    cli={
                        "options": {
                            "android.deviceId": {
                                "preferredName": "device-id",
                                "aliases": ["deviceId"],
                            }
                        }
                    },
                )
            ]
        )

        with pytest.raises(CLIError) as error:
            await run_tools_cli(
                tools,
                "midscene-android",
                {
                    "stripPrefix": "android_",
                    "argv": ["connect", "--android.deviceId", "emulator-5554"],
                },
            )
        assert (
            str(error.value)
            == 'Unsupported option "--android.deviceId" for midscene-android connect.'
        )

    @pytest.mark.asyncio
    async def test_throws_cli_error_for_unknown_command(self, capsys):
        tools = _FakeTools([_tool("connect")])

        with pytest.raises(CLIError):
            await run_tools_cli(tools, "test-cli", {"argv": ["unknown"]})
        assert "Unknown command: unknown" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_executes_matched_command_with_parsed_args(self, capsys):
        received = []

        async def handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "Connected"}])

        tools = _FakeTools([_tool("test_connect", handler=handler)])
        await run_tools_cli(
            tools,
            "test-cli",
            {"stripPrefix": "test_", "argv": ["connect", "--url", "https://example.com"]},
        )

        assert received == [{"url": "https://example.com"}]
        assert "Connected" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_maps_leading_command_positionals_into_handler_arguments(self):
        received = []

        async def handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "Recording started"}])

        tools = _FakeTools(
            [],
            [
                _tool(
                    "record",
                    handler=handler,
                    schema={
                        "action": {"type": "literal", "value": "start"},
                        "output": {"type": "string", "optional": True},
                    },
                    cli={"positionals": ["action"]},
                )
            ],
        )
        await run_tools_cli(
            tools, "test-cli", {"argv": ["record", "start", "--output", "toast.json"]}
        )

        assert received == [{"action": "start", "output": "toast.json"}]

    @pytest.mark.asyncio
    async def test_strips_global_verbose_and_emits_readable_progress_lines(
        self, capsys
    ):
        async def handler(_args):
            return ToolResult([{"type": "text", "text": "Connected"}])

        tools = _FakeTools([_tool("connect", handler=handler)])
        await run_tools_cli(
            tools,
            "test-cli",
            {"argv": ["--verbose", "connect", "--url", "https://example.com"]},
        )

        messages = [line for line in capsys.readouterr().out.splitlines() if line]
        assert messages[0] == "[Midscene] connect started (url=https://example.com)"
        assert messages[1] == "Connected"
        assert re.match(r"^\[Midscene\] connect finished in \d+(\.\d+)?ms$", messages[2])

    @pytest.mark.asyncio
    async def test_emits_readable_progress_for_record_without_an_explicit_verbose_flag(
        self, capsys
    ):
        async def handler(_args):
            return ToolResult([{"type": "text", "text": "Observation passed"}])

        tools = _FakeTools([_tool("record", handler=handler)])
        await run_tools_cli(
            tools, "test-cli", {"argv": ["record", "--output", "toast.json"]}
        )

        messages = [line for line in capsys.readouterr().out.splitlines() if line]
        assert messages[0] == "[Midscene] record started (output=toast.json)"
        assert messages[1] == "Observation passed"
        assert re.match(r"^\[Midscene\] record finished in \d+(\.\d+)?ms$", messages[2])

    @pytest.mark.asyncio
    async def test_preserves_structured_command_args_in_jsonl_verbose_progress_events(
        self, capsys
    ):
        async def handler(_args):
            return ToolResult([{"type": "text", "text": "Tapped"}])

        tools = _FakeTools([_tool("tap", handler=handler)])
        await run_tools_cli(
            tools,
            "test-cli",
            {
                "argv": [
                    "--verbose=jsonl",
                    "tap",
                    "--locate",
                    '{"prompt":"Submit","deepLocate":true}',
                ]
            },
        )

        progress_events = []
        for line in capsys.readouterr().out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "midscene_progress":
                progress_events.append(event)

        assert progress_events[0]["event"] == "command_start"
        assert progress_events[0]["scriptName"] == "test-cli"
        assert progress_events[0]["command"] == "tap"
        assert progress_events[0]["args"] == {
            "locate": {"prompt": "Submit", "deepLocate": True}
        }

    @pytest.mark.asyncio
    async def test_strips_platform_prefix_from_command_names(self):
        received = []

        async def handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("android_disconnect", handler=handler)])
        await run_tools_cli(
            tools, "test-cli", {"stripPrefix": "android_", "argv": ["disconnect"]}
        )

        assert received == [{}]

    @pytest.mark.asyncio
    async def test_calls_destroy_after_successful_command(self):
        tools = _FakeTools([_tool("connect")])
        await run_tools_cli(tools, "test-cli", {"argv": ["connect"]})

        assert tools.destroyed == 1

    @pytest.mark.asyncio
    async def test_calls_destroy_before_throwing_on_command_error(self):
        async def handler(_args):
            return ToolResult(
                [{"type": "text", "text": "Something went wrong"}], is_error=True
            )

        tools = _FakeTools([_tool("fail_cmd", handler=handler)])
        with pytest.raises(CLIError):
            await run_tools_cli(
                tools, "test-cli", {"stripPrefix": "", "argv": ["fail_cmd"]}
            )

        assert tools.destroyed == 1

    @pytest.mark.asyncio
    async def test_calls_destroy_when_a_command_handler_throws(self):
        async def handler(_args):
            raise RuntimeError("boom")

        tools = _FakeTools([_tool("explode", handler=handler)])
        with pytest.raises(RuntimeError, match="boom"):
            await run_tools_cli(tools, "test-cli", {"argv": ["--verbose", "explode"]})

        assert tools.destroyed == 1

    @pytest.mark.asyncio
    async def test_emits_an_ai_act_failure_line_when_an_act_command_throws_by_default(
        self, capsys
    ):
        async def handler(_args):
            raise RuntimeError("boom")

        tools = _FakeTools([_tool("act", handler=handler)])
        with pytest.raises(RuntimeError, match="boom"):
            await run_tools_cli(tools, "test-cli", {"argv": ["act"]})

        assert "[Midscene][aiAct] Failed: boom" in capsys.readouterr().out
        assert tools.destroyed == 1

    @pytest.mark.asyncio
    async def test_matches_commands_case_insensitively(self):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "tapped"}])

        tools = _FakeTools([_tool("Tap", handler=handler)])

        await run_tools_cli(tools, "test-cli", {"argv": ["tap"]})
        assert len(calls) == 1

        await run_tools_cli(tools, "test-cli", {"argv": ["Tap"]})
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_displays_command_names_as_lowercase_in_help(self, capsys):
        tools = _FakeTools([_tool("Tap"), _tool("Scroll")])
        await run_tools_cli(tools, "test-cli", {"argv": ["--help"]})

        output = capsys.readouterr().out
        assert "  tap" in output
        assert "  scroll" in output

        lines = output.splitlines()
        command_lines = lines[
            lines.index("Commands:") + 1 : lines.index("Global Options:")
        ]
        for line in command_lines:
            if not line.startswith("  "):
                continue
            command_name = re.split(r"\s{2,}", line.strip())[0]
            assert command_name == command_name.lower()

    @pytest.mark.asyncio
    async def test_shows_command_help_with_help_after_command_name(self, capsys):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools([_tool("connect", handler=handler)])
        await run_tools_cli(tools, "test-cli", {"argv": ["connect", "--help"]})

        assert calls == []
        assert "Usage: test-cli connect [options]" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_shows_foreground_record_help_without_session_or_end_plumbing(
        self, capsys
    ):
        tools = _FakeTools(
            [],
            [
                _tool(
                    "record",
                    description="record command",
                    schema={
                        "action": {"type": "literal", "value": "start"},
                        "output": {"type": "string", "optional": True},
                    },
                    cli={"positionals": ["action"]},
                )
            ],
        )
        await run_tools_cli(tools, "test-cli", {"argv": ["record", "--help"]})

        output = capsys.readouterr().out
        assert "Usage: test-cli record <action> [options]" in output
        assert "--output" in output
        assert "--session" not in output
        assert "Global Options:" in output

    @pytest.mark.asyncio
    async def test_supports_shared_extra_commands(self, capsys):
        received = []

        async def extra_handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "split done"}])

        tools = _FakeTools([])
        await run_tools_cli(
            tools,
            "test-cli",
            {
                "argv": [
                    "report-tool",
                    "--action",
                    "split",
                    "--htmlPath",
                    "./in.html",
                    "--outputDir",
                    "./out",
                ],
                "extraCommands": [
                    {
                        "name": "report-tool",
                        "def": _tool(
                            "report-tool",
                            handler=extra_handler,
                            description="report tools",
                        ),
                    }
                ],
            },
        )

        assert received == [
            {"htmlPath": "./in.html", "outputDir": "./out", "action": "split"}
        ]
        assert "split done" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_canonicalizes_kebab_case_spellings_to_schema_keys_before_dispatch(
        self,
    ):
        received = []

        async def handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools(
            [
                _tool(
                    "assert",
                    handler=handler,
                    schema={
                        "prompt": {"type": "string"},
                        "imageName": {
                            "type": "string|string[]",
                            "optional": True,
                        },
                    },
                )
            ]
        )
        await run_tools_cli(
            tools,
            "test-cli",
            {
                "argv": [
                    "assert",
                    "--prompt",
                    "p",
                    "--image-name",
                    "a",
                    "--image-name",
                    "b",
                ]
            },
        )

        assert received == [{"prompt": "p", "imageName": ["a", "b"]}]

    @pytest.mark.asyncio
    async def test_canonicalizes_aliases_while_preserving_numeric_looking_strings(
        self,
    ):
        received = []

        async def handler(args):
            received.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools(
            [
                _tool(
                    "android_connect",
                    handler=handler,
                    schema={"android.deviceId": {"type": "string", "optional": True}},
                    cli={
                        "options": {
                            "android.deviceId": {
                                "preferredName": "device-id",
                                "aliases": ["deviceId"],
                            }
                        }
                    },
                )
            ]
        )
        await run_tools_cli(
            tools,
            "midscene-android",
            {
                "stripPrefix": "android_",
                "argv": ["connect", "--deviceId", "320336557157"],
            },
        )

        assert received == [{"android.deviceId": "320336557157"}]

    @pytest.mark.asyncio
    async def test_throws_cli_error_when_the_same_field_is_set_under_conflicting_spellings(
        self,
    ):
        calls = []

        async def handler(args):
            calls.append(args)
            return ToolResult([{"type": "text", "text": "ok"}])

        tools = _FakeTools(
            [
                _tool(
                    "assert",
                    handler=handler,
                    schema={
                        "prompt": {"type": "string"},
                        "imageName": {"type": "string", "optional": True},
                    },
                )
            ]
        )
        with pytest.raises(CLIError, match=r"Conflicting CLI options.*image-name"):
            await run_tools_cli(
                tools,
                "test-cli",
                {
                    "argv": [
                        "assert",
                        "--prompt",
                        "p",
                        "--imageName",
                        "camel",
                        "--image-name",
                        "kebab",
                    ]
                },
            )

        assert calls == []
