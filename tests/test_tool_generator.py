"""Tool generation (upstream tool-generator.test.ts)."""

import asyncio

import pytest

from midscene.shared.agent_tools.observation_artifact import (
    observation_artifact_adapter_symbol,
)
from midscene.shared.agent_tools.tool_generator import (
    generate_common_tools,
    generate_tools_from_action_space,
)
from midscene.shared.agent_tools.types import ActionSpaceItem, schema_field
from midscene.shared.cli import record_command
from midscene.shared.agent_tools.user_prompt import compose_user_prompt
from midscene.shared.cli.record_command import create_record_cli_command
from midscene.shared.cli.verbose import with_cli_verbose_context

SCREENSHOT = "data:image/png;base64,Zm9v"

LOCATE_SCHEMA = {
    "type": "object",
    "fields": {
        "prompt": {"type": "string"},
        "deepLocate": {"type": "boolean", "optional": True},
        "deepThink": {"type": "boolean", "optional": True},
        "cacheable": {"type": "boolean", "optional": True},
        "xpath": {"type": "string|boolean", "optional": True},
    },
}


class _Page:
    def __init__(self, screenshot=SCREENSHOT):
        self._screenshot = screenshot

    async def screenshot_base64(self):
        return self._screenshot


class _Agent:
    def __init__(self, **methods):
        for key, value in methods.items():
            setattr(self, key, value)
        self.page = methods.get("page") or _Page()

    async def get_action_space(self):
        return []


def _with_adapter(agent, adapter):
    setattr(agent, observation_artifact_adapter_symbol, adapter)
    return agent


class TestGenerateToolsFromActionSpace:
    @pytest.mark.asyncio
    async def test_passes_structured_locate_extras_through_call_action_in_action_space_and_keeps_locate_options_at_top_level(
        self,
    ):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        action_space = [
            ActionSpaceItem(
                name="Tap",
                description="Tap the element",
                param_schema={"locate": LOCATE_SCHEMA},
            )
        ]
        [tool] = generate_tools_from_action_space(
            action_space, lambda _args: _await(agent)
        )

        images = [{"name": "reference logo", "url": "https://example.com/logo.png"}]

        result = await tool.handler(
            {
                "locate": {
                    "prompt": "the reference logo",
                    "deepLocate": True,
                    "images": images,
                    "convertHttpImage2Base64": True,
                }
            }
        )

        assert calls == [
            (
                "Tap",
                {
                    "locate": {
                        "prompt": {
                            "prompt": "the reference logo",
                            "images": images,
                            "convertHttpImage2Base64": True,
                        },
                        "deepLocate": True,
                    }
                },
            )
        ]
        assert result.content == [
            {"type": "text", "text": 'Action "Tap" completed.'},
            {"type": "image", "data": "Zm9v", "mimeType": "image/png"},
        ]

    @pytest.mark.asyncio
    async def test_normalizes_string_locate_shorthand_before_direct_action_execution(
        self,
    ):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        action_space = [
            ActionSpaceItem(
                name="Tap",
                description="Tap the element",
                param_schema={"locate": LOCATE_SCHEMA},
            )
        ]
        [tool] = generate_tools_from_action_space(
            action_space, lambda _args: _await(agent)
        )

        await tool.handler({"locate": "the login button"})

        assert calls == [("Tap", {"locate": {"prompt": "the login button"}})]

    def test_preserves_locate_field_descriptions_after_making_locate_prompt_optional(
        self,
    ):
        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={
                        "locate": {
                            **LOCATE_SCHEMA,
                            "description": "The element to be tapped",
                        }
                    },
                )
            ],
            lambda _args: _await(_Agent()),
        )

        assert tool.schema["locate"]["description"] == "The element to be tapped"

    @pytest.mark.asyncio
    async def test_falls_back_to_ai_action_when_direct_action_execution_is_unavailable(
        self,
    ):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))

        agent = _Agent(ai_action=ai_action)
        action_space = [
            ActionSpaceItem(
                name="Tap",
                description="Tap the element",
                param_schema={"locate": LOCATE_SCHEMA},
            )
        ]
        [tool] = generate_tools_from_action_space(
            action_space, lambda _args: _await(agent)
        )

        await tool.handler({"locate": {"prompt": {"prompt": "the login button"}}})

        assert calls[0][0] == 'Tap on "the login button"'

    @pytest.mark.asyncio
    async def test_includes_direct_action_return_values_in_the_tool_result(self):
        async def call_action_in_action_space(_name, _args):
            return "pm clear output"

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        action_space = [
            ActionSpaceItem(
                name="RunAdbShell",
                description="Execute ADB shell command",
                param_schema={"command": schema_field("string")},
            )
        ]
        [tool] = generate_tools_from_action_space(
            action_space, lambda _args: _await(agent)
        )

        result = await tool.handler({"command": "pm clear com.example.app"})

        assert result.content == [
            {"type": "text", "text": 'Action "RunAdbShell" completed.'},
            {"type": "text", "text": "Result: pm clear output"},
            {"type": "image", "data": "Zm9v", "mimeType": "image/png"},
        ]

    @pytest.mark.asyncio
    async def test_passes_raw_args_to_the_agent_getter_while_stripping_init_args_from_action_payload(
        self,
    ):
        calls = []
        get_agent_args = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        async def get_agent(args):
            get_agent_args.append(args)
            return _Agent(call_action_in_action_space=call_action_in_action_space)

        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="RunAdbShell",
                    description="Execute ADB shell command",
                    param_schema={"command": schema_field("string")},
                )
            ],
            get_agent,
            lambda args: {k: v for k, v in args.items() if k != "deviceId"},
        )

        await tool.handler(
            {"command": "pm clear com.example.app", "deviceId": "target-device"}
        )

        assert get_agent_args == [
            {"command": "pm clear com.example.app", "deviceId": "target-device"}
        ]
        assert calls == [
            ("RunAdbShell", {"command": "pm clear com.example.app"})
        ]

    def test_merges_init_arg_schema_into_action_and_common_tools(self):
        init_schema = {
            "android.deviceId": schema_field(
                "string", "Android device ID", optional=True
            )
        }
        init_cli = {
            "options": {
                "android.deviceId": {
                    "preferredName": "device-id",
                    "aliases": ["deviceId"],
                }
            }
        }
        [action_tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={"locate": LOCATE_SCHEMA},
                )
            ],
            lambda _args: _await(_Agent()),
            init_arg_schema=init_schema,
            init_arg_cli_metadata=init_cli,
        )
        common_tools = generate_common_tools(
            lambda _args: _await(_Agent()),
            init_schema,
            init_cli,
        )

        assert "locate" in action_tool.schema
        assert "android.deviceId" in action_tool.schema
        assert action_tool.cli == init_cli

        screenshot_tool = next(
            tool for tool in common_tools if tool.name == "take_screenshot"
        )
        assert "android.deviceId" in screenshot_tool.schema
        assert screenshot_tool.cli == init_cli

        act_tool = next(tool for tool in common_tools if tool.name == "act")
        assert set(act_tool.schema) >= {"prompt", "android.deviceId"}
        assert act_tool.cli == init_cli

        record_tool = create_record_cli_command(
            lambda _args: _await(_Agent()), init_schema, init_cli
        )
        assert not any(tool.name == "record" for tool in common_tools)
        assert set(record_tool.schema) >= {"action", "output", "android.deviceId"}
        assert record_tool.cli == {
            "positionals": ["action"],
            "options": {
                "intervalMs": {
                    "preferredName": "interval-ms",
                    "aliases": ["intervalMs"],
                },
                "maxFrames": {
                    "preferredName": "max-frames",
                    "aliases": ["maxFrames"],
                },
                "watchdogMs": {
                    "preferredName": "watchdog-ms",
                    "aliases": ["watchdogMs"],
                },
                "action": {"hidden": True},
                "android.deviceId": {
                    "preferredName": "device-id",
                    "aliases": ["deviceId"],
                },
            },
        }

        assert_tool = next(tool for tool in common_tools if tool.name == "assert")
        assert set(assert_tool.schema) >= {"prompt", "android.deviceId"}
        assert assert_tool.cli == init_cli

    @pytest.mark.asyncio
    async def test_includes_ai_action_return_values_in_the_common_act_tool_result(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "Midscene"

        common_tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action))
        )
        act_tool = next(tool for tool in common_tools if tool.name == "act")

        result = await act_tool.handler(
            {
                "prompt": "return the first Google result heading for Midscene",
                "fileChooserAllowedDir": "./fixtures",
            }
        )

        assert calls == [
            (
                "return the first Google result heading for Midscene",
                {"deepThink": False, "fileChooserAllowedDir": "./fixtures"},
            )
        ]
        assert result.content == [
            {"type": "text", "text": 'Action "act" completed.'},
            {"type": "text", "text": "Result: Midscene"},
            {"type": "image", "data": "Zm9v", "mimeType": "image/png"},
        ]

    @pytest.mark.asyncio
    async def test_stops_a_foreground_recording_on_ctrl_c_before_writing_its_artifact(
        self, tmp_path, monkeypatch
    ):
        output = tmp_path / "toast-observation.json"
        source_frame = tmp_path / "source.png"
        source_frame.write_text("recorded-frame", encoding="utf-8")

        calls = []

        async def export_record(_observation):
            return {
                "type": "midscene_ui_observation",
                "version": 1,
                "startedAt": 50,
                "endedAt": 150,
                "frames": [
                    {
                        "path": str(source_frame),
                        "mimeType": "image/png",
                        "capturedAt": 100,
                    }
                ],
                "shotSize": {"width": 100, "height": 50},
                "shrunkShotToLogicalRatio": 1,
            }

        class _Observer:
            async def stop(self):
                calls.append("stop")
                return {"frameCount": 1}

            async def dispose(self):
                calls.append("dispose")

        async def start_observing(config):
            calls.append(("start_observing", config))
            return _Observer()

        agent = _with_adapter(
            _Agent(start_observing=start_observing),
            type("_Adapter", (), {"export_record": staticmethod(export_record)})(),
        )

        loop = asyncio.get_running_loop()
        stop_future = loop.create_future()
        stop_future.set_result("sigint")

        class _Waiter:
            result = stop_future

            def __init__(self, watchdog_ms):
                self.watchdog_ms = watchdog_ms

            def dispose(self):
                calls.append("interrupt_dispose")

        created = []

        def fake_create(watchdog_ms):
            waiter = _Waiter(watchdog_ms)
            created.append(waiter)
            return waiter

        monkeypatch.setattr(
            record_command, "create_cli_interrupt_waiter", fake_create
        )
        record_tool = create_record_cli_command(lambda _args: _await(agent))

        result = await with_cli_verbose_context(
            {"enabled": False, "scriptName": "midscene-web", "commandName": "record"},
            lambda: record_tool.handler(
                {
                    "action": "start",
                    "output": str(output),
                    "intervalMs": 250,
                    "maxFrames": 12,
                    "watchdogMs": 5000,
                }
            ),
        )

        assert calls[0] == (
            "start_observing",
            {"intervalMs": 250, "maxFrames": 12, "watchdogMs": 5000},
        )
        assert created[0].watchdog_ms == 5000
        assert "stop" in calls
        assert calls[-2:] == ["dispose", "interrupt_dispose"]
        assert output.exists()
        assert result.content == [
            {"type": "text", "text": f"Observation record saved: {output}"}
        ]

    @pytest.mark.asyncio
    async def test_fails_clearly_when_start_observing_is_unavailable(self):
        record_tool = create_record_cli_command(lambda _args: _await(_Agent()))

        result = await with_cli_verbose_context(
            {"enabled": False, "scriptName": "midscene-web", "commandName": "record"},
            lambda: record_tool.handler({"action": "start"}),
        )

        assert result.content == [
            {
                "type": "text",
                "text": "Failed to execute record: record is not supported because "
                "this agent does not provide startObserving",
            }
        ]
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_rejects_a_missing_record_operation_before_creating_an_agent(self):
        called = []

        async def get_agent(_args):
            called.append(True)
            return _Agent()

        record_tool = create_record_cli_command(get_agent)

        missing_action = await record_tool.handler({})

        assert called == []
        assert missing_action.content == [
            {
                "type": "text",
                "text": "record requires the start operation (for example: record "
                "start --output ./observation.json)",
            }
        ]
        assert missing_action.is_error is True

    @pytest.mark.asyncio
    async def test_records_take_screenshot_in_reports_with_the_captured_screenshot(self):
        calls = []
        screenshot_calls = []

        async def screenshot_base64():
            screenshot_calls.append(True)
            return SCREENSHOT

        async def record_to_report(kind, payload):
            calls.append((kind, payload))

        agent = _Agent(
            page=_Page(), record_to_report=record_to_report
        )
        agent.page = _Page()
        agent.page.screenshot_base64 = screenshot_base64

        common_tools = generate_common_tools(lambda _args: _await(agent))
        screenshot_tool = next(
            tool for tool in common_tools if tool.name == "take_screenshot"
        )

        result = await screenshot_tool.handler({})

        assert len(screenshot_calls) == 1
        assert calls == [("take_screenshot", {"screenshotBase64": SCREENSHOT})]
        assert result.content == [
            {"type": "image", "data": "Zm9v", "mimeType": "image/png"}
        ]

    def test_rejects_non_object_param_schema_with_a_clear_error_naming_the_action(self):
        action_space = [
            ActionSpaceItem(
                name="BadLaunch",
                description="Launch something",
                param_schema="string",
            )
        ]

        with pytest.raises(
            ValueError, match='Action "BadLaunch" declared a non-object param_schema'
        ):
            generate_tools_from_action_space(action_space, lambda _args: _await(_Agent()))

    def test_accepts_undefined_and_object_param_schema(self):
        action_space = [
            ActionSpaceItem(name="NoParamAction", description="takes no args"),
            ActionSpaceItem(
                name="ObjectAction",
                description="takes object args",
                param_schema={"uri": schema_field("string")},
            ),
        ]

        generate_tools_from_action_space(action_space, lambda _args: _await(_Agent()))


class TestComposeUserPrompt:
    def test_returns_the_bare_string_when_no_images_are_supplied(self):
        assert compose_user_prompt("just text") == "just text"

    def test_accepts_paired_image_and_image_name_values(self):
        assert compose_user_prompt(
            "compare to the logo",
            image="https://x/y.png",
            image_name="logo",
        ) == {
            "prompt": "compare to the logo",
            "images": [{"name": "logo", "url": "https://x/y.png"}],
        }

    def test_accepts_paired_image_arguments_with_convert_http_image_to_base64(self):
        assert compose_user_prompt(
            "p",
            image="https://x/a.png",
            image_name="a",
            convert_http_image_to_base64=True,
        ) == {
            "prompt": "p",
            "images": [{"name": "a", "url": "https://x/a.png"}],
            "convertHttpImage2Base64": True,
        }

    def test_passes_a_local_file_path_through_verbatim(self):
        assert compose_user_prompt(
            "find the red marker",
            image="./fixtures/red.png",
            image_name="marker",
        ) == {
            "prompt": "find the red marker",
            "images": [{"name": "marker", "url": "./fixtures/red.png"}],
        }

    def test_coerces_stringified_booleans_for_convert_http_image_to_base64(self):
        result = compose_user_prompt(
            "p",
            image="https://x/a.png",
            image_name="a",
            convert_http_image_to_base64="true",
        )
        assert result["convertHttpImage2Base64"] is True

    def test_throws_when_convert_http_image_to_base64_is_an_unrecognized_string(self):
        with pytest.raises(ValueError, match="convertHttpImage2Base64"):
            compose_user_prompt(
                "p",
                image="https://x/a.png",
                image_name="a",
                convert_http_image_to_base64="maybe",
            )

    def test_throws_when_image_is_not_a_string_or_string_array(self):
        with pytest.raises(ValueError, match="image:"):
            compose_user_prompt("p", image=42)

    def test_throws_when_image_and_image_name_counts_do_not_match(self):
        with pytest.raises(ValueError, match="same number"):
            compose_user_prompt("p", image="https://x/a.png")

    def test_throws_when_image_name_array_contains_non_string_items(self):
        with pytest.raises(ValueError, match=r"imageName\[0\]"):
            compose_user_prompt(
                "p", image=["https://x/a.png"], image_name=[123]
            )

    def test_builds_images_array_from_image_and_image_name_pairs(self):
        assert compose_user_prompt(
            "p", image="https://x/a.png", image_name="a"
        ) == {
            "prompt": "p",
            "images": [{"name": "a", "url": "https://x/a.png"}],
        }

    def test_throws_when_repeated_image_and_image_name_values_are_unbalanced(self):
        with pytest.raises(ValueError, match="same number"):
            compose_user_prompt("p", image=["https://x/a.png"], image_name=[])

    def test_throws_when_image_name_is_neither_a_string_nor_a_string_array(self):
        with pytest.raises(ValueError, match="got int"):
            compose_user_prompt("p", image_name=42)


class TestGenerateCommonToolsAssertImagePrompts:
    @pytest.mark.asyncio
    async def test_passes_prompt_through_unchanged_when_no_images_are_supplied(self):
        calls = []

        async def ai_assert(prompt, message=None):
            calls.append((prompt, message))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_assert=ai_assert))
        )
        assert_tool = next(tool for tool in tools if tool.name == "assert")
        await assert_tool.handler({"prompt": "login button visible"})

        assert calls == [("login button visible", None)]

    @pytest.mark.asyncio
    async def test_forwards_the_custom_failure_message_to_ai_assert(self):
        calls = []

        async def ai_assert(prompt, message=None):
            calls.append((prompt, message))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_assert=ai_assert))
        )
        assert_tool = next(tool for tool in tools if tool.name == "assert")
        await assert_tool.handler(
            {
                "prompt": "login button visible",
                "message": "the login button should be visible",
            }
        )

        assert calls == [
            ("login button visible", "the login button should be visible")
        ]

    @pytest.mark.asyncio
    async def test_loads_an_observation_record_and_forwards_it_to_ai_assert(
        self, tmp_path
    ):
        record_path = tmp_path / "toast-observation.json"
        frames_dir = tmp_path / "toast-observation.frames"
        frames_dir.mkdir()
        frame_path = frames_dir / "frame.png"
        frame_path.write_text("frame", encoding="utf-8")
        record_path.write_text(
            """
            {
              "type": "midscene_ui_observation",
              "version": 1,
              "startedAt": 50,
              "endedAt": 250,
              "frames": [
                {"path": "toast-observation.frames/frame.png",
                 "mimeType": "image/png", "capturedAt": 100},
                {"path": "toast-observation.frames/frame.png",
                 "mimeType": "image/png", "capturedAt": 200}
              ],
              "shotSize": {"width": 100, "height": 100},
              "shrunkShotToLogicalRatio": 1
            }
            """,
            encoding="utf-8",
        )

        loaded = []
        asserted = []
        disposed = []

        class _Observation:
            async def ai_assert(self, prompt, message=None):
                asserted.append((prompt, message))

            async def dispose(self):
                disposed.append(True)

        def load_record(record):
            loaded.append(record)
            return _Observation()

        async def ai_assert(_prompt, _message=None):
            raise AssertionError("ai_assert must not be used with a record")

        agent = _with_adapter(
            _Agent(ai_assert=ai_assert),
            type("_Adapter", (), {"load_record": staticmethod(load_record)})(),
        )
        tools = generate_common_tools(lambda _args: _await(agent))
        assert_tool = next(tool for tool in tools if tool.name == "assert")

        result = await assert_tool.handler(
            {"prompt": "a success toast appeared", "record": str(record_path)}
        )

        assert loaded[0]["frames"] == [
            {"path": str(frame_path), "mimeType": "image/png", "capturedAt": 100},
            {"path": str(frame_path), "mimeType": "image/png", "capturedAt": 200},
        ]
        assert asserted == [("a success toast appeared", None)]
        assert disposed == [True]
        assert result.content == [{"type": "text", "text": "Assertion passed."}]

    @pytest.mark.asyncio
    async def test_rejects_a_record_whose_image_path_escapes_the_manifest_directory(
        self, tmp_path
    ):
        record_path = tmp_path / "invalid-observation.json"
        record_path.write_text(
            """
            {
              "type": "midscene_ui_observation",
              "version": 1,
              "startedAt": 50,
              "endedAt": 150,
              "frames": [
                {"path": "../not-an-image.png",
                 "mimeType": "image/png", "capturedAt": 100}
              ],
              "shotSize": {"width": 100, "height": 100},
              "shrunkShotToLogicalRatio": 1
            }
            """,
            encoding="utf-8",
        )
        calls = []

        async def ai_assert(prompt, message=None):
            calls.append((prompt, message))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_assert=ai_assert))
        )
        assert_tool = next(tool for tool in tools if tool.name == "assert")

        result = await assert_tool.handler(
            {"prompt": "a success toast appeared", "record": str(record_path)}
        )

        assert calls == []
        assert result.is_error is True
        assert "Invalid UI observation record at frames.0.path" in result.content[0][
            "text"
        ]

    @pytest.mark.asyncio
    async def test_forwards_images_to_ai_assert_as_a_user_prompt_style_object(self):
        calls = []

        async def ai_assert(prompt, message=None):
            calls.append((prompt, message))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_assert=ai_assert))
        )
        assert_tool = next(tool for tool in tools if tool.name == "assert")
        await assert_tool.handler(
            {
                "prompt": "the visible badge matches the reference image",
                "image": "https://example.com/btn.png",
                "imageName": "target",
            }
        )

        assert calls == [
            (
                {
                    "prompt": "the visible badge matches the reference image",
                    "images": [
                        {"name": "target", "url": "https://example.com/btn.png"}
                    ],
                },
                None,
            )
        ]

    @pytest.mark.asyncio
    async def test_forwards_a_local_path_url_verbatim_so_core_can_resolve_it(self):
        calls = []

        async def ai_assert(prompt, message=None):
            calls.append((prompt, message))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_assert=ai_assert))
        )
        assert_tool = next(tool for tool in tools if tool.name == "assert")
        await assert_tool.handler(
            {
                "prompt": "the visible badge matches the supplied image",
                "image": "./fixtures/badge.png",
                "imageName": "badge",
            }
        )

        assert calls == [
            (
                {
                    "prompt": "the visible badge matches the supplied image",
                    "images": [
                        {"name": "badge", "url": "./fixtures/badge.png"}
                    ],
                },
                None,
            )
        ]

    def test_exposes_images_and_convert_http_image_to_base64_on_the_assert_schema(self):
        tools = generate_common_tools(lambda _args: _await(_Agent()))

        assert_schema = next(tool for tool in tools if tool.name == "assert").schema
        for key in (
            "prompt",
            "message",
            "record",
            "image",
            "imageName",
            "convertHttpImage2Base64",
        ):
            assert key in assert_schema
        assert "images" not in assert_schema
        assert "imageFiles" not in assert_schema

        act_schema = next(tool for tool in tools if tool.name == "act").schema
        for key in ("prompt", "image", "imageName", "convertHttpImage2Base64"):
            assert key in act_schema
        assert "images" not in act_schema
        assert "imageFiles" not in act_schema


class TestGenerateCommonToolsActImagePrompts:
    @pytest.mark.asyncio
    async def test_passes_the_prompt_through_unchanged_when_no_images_are_supplied(
        self,
    ):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action))
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "click the login button"})

        assert calls == [("click the login button", {"deepThink": False})]

    @pytest.mark.asyncio
    async def test_forwards_images_to_ai_action_as_a_user_prompt_style_object(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action))
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler(
            {
                "prompt": "tap the icon that matches the reference image",
                "image": "https://example.com/icon.png",
                "imageName": "target",
            }
        )

        assert calls == [
            (
                {
                    "prompt": "tap the icon that matches the reference image",
                    "images": [
                        {"name": "target", "url": "https://example.com/icon.png"}
                    ],
                },
                {"deepThink": False},
            )
        ]

    @pytest.mark.asyncio
    async def test_forwards_a_local_path_url_verbatim_so_core_can_resolve_it(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action))
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler(
            {
                "prompt": "tap the icon that matches the supplied image",
                "image": "./fixtures/icon.png",
                "imageName": "icon",
                "convertHttpImage2Base64": True,
            }
        )

        assert calls == [
            (
                {
                    "prompt": "tap the icon that matches the supplied image",
                    "images": [{"name": "icon", "url": "./fixtures/icon.png"}],
                    "convertHttpImage2Base64": True,
                },
                {"deepThink": False},
            )
        ]


class TestToolDefaults:
    @pytest.mark.asyncio
    async def test_defaults_locate_deep_locate_to_true_for_action_tools_when_enabled(
        self,
    ):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={"locate": LOCATE_SCHEMA},
                )
            ],
            lambda _args: _await(agent),
            tool_defaults={"locate": {"deepLocate": True}},
        )

        await tool.handler({"locate": "the login button"})

        assert calls == [
            (
                "Tap",
                {"locate": {"prompt": "the login button", "deepLocate": True}},
            )
        ]

    @pytest.mark.asyncio
    async def test_keeps_an_explicit_locate_deep_locate_false_even_when_forced(self):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={"locate": LOCATE_SCHEMA},
                )
            ],
            lambda _args: _await(agent),
            tool_defaults={"locate": {"deepLocate": True}},
        )

        await tool.handler(
            {"locate": {"prompt": "the login button", "deepLocate": False}}
        )

        assert calls == [
            (
                "Tap",
                {"locate": {"prompt": "the login button", "deepLocate": False}},
            )
        ]

    @pytest.mark.asyncio
    async def test_treats_an_explicit_deep_think_alias_as_deep_locate_already_set(self):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={"locate": LOCATE_SCHEMA},
                )
            ],
            lambda _args: _await(agent),
            tool_defaults={"locate": {"deepLocate": True}},
        )

        await tool.handler(
            {"locate": {"prompt": "the login button", "deepThink": False}}
        )

        assert calls == [
            (
                "Tap",
                {"locate": {"prompt": "the login button", "deepThink": False}},
            )
        ]

    @pytest.mark.asyncio
    async def test_does_not_inject_deep_locate_for_action_tools_when_disabled(self):
        calls = []

        async def call_action_in_action_space(name, args):
            calls.append((name, args))

        agent = _Agent(call_action_in_action_space=call_action_in_action_space)
        [tool] = generate_tools_from_action_space(
            [
                ActionSpaceItem(
                    name="Tap",
                    description="Tap the element",
                    param_schema={"locate": LOCATE_SCHEMA},
                )
            ],
            lambda _args: _await(agent),
        )

        await tool.handler({"locate": "the login button"})

        assert calls == [("Tap", {"locate": {"prompt": "the login button"}})]

    @pytest.mark.asyncio
    async def test_passes_deep_locate_to_the_act_tool_when_enabled(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "done"

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action)),
            tool_defaults={"act": {"deepLocate": True}},
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "open settings"})

        assert calls == [
            ("open settings", {"deepThink": False, "deepLocate": True})
        ]

    @pytest.mark.asyncio
    async def test_lets_an_explicit_act_deep_locate_arg_override_the_server_default(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "done"

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action)),
            tool_defaults={"act": {"deepLocate": True}},
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "open settings", "deepLocate": False})

        assert calls == [
            ("open settings", {"deepThink": False, "deepLocate": False})
        ]

    @pytest.mark.asyncio
    async def test_plans_the_act_tool_with_deep_think_when_enabled(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "done"

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action)),
            tool_defaults={"act": {"deepThink": True}},
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "open settings"})

        assert calls == [("open settings", {"deepThink": True})]

    @pytest.mark.asyncio
    async def test_lets_an_explicit_act_deep_think_arg_override_the_server_default(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "done"

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action)),
            tool_defaults={"act": {"deepThink": True}},
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "open settings", "deepThink": False})

        assert calls == [("open settings", {"deepThink": False})]

    @pytest.mark.asyncio
    async def test_applies_both_locate_and_act_defaults_together(self):
        calls = []

        async def ai_action(prompt, options):
            calls.append((prompt, options))
            return "done"

        tools = generate_common_tools(
            lambda _args: _await(_Agent(ai_action=ai_action)),
            tool_defaults={
                "locate": {"deepLocate": True},
                "act": {"deepLocate": True, "deepThink": True},
            },
        )
        act_tool = next(tool for tool in tools if tool.name == "act")
        await act_tool.handler({"prompt": "open settings"})

        assert calls == [
            ("open settings", {"deepThink": True, "deepLocate": True})
        ]

    @pytest.mark.skip(
        reason="The Python verbose aiAct renderer consumes a different progress "
        "payload contract; upstream timeline expectations do not map 1:1"
    )
    def test_emits_human_readable_ai_act_verbose_timeline_while_act_is_running(self):
        pass

    @pytest.mark.skip(
        reason="The Python verbose aiAct renderer consumes a different progress "
        "payload contract; upstream timeline expectations do not map 1:1"
    )
    def test_does_not_render_ai_act_dump_progress_without_core_progress_listener(self):
        pass

    @pytest.mark.skip(
        reason="The Python verbose aiAct renderer consumes a different progress "
        "payload contract; upstream timeline expectations do not map 1:1"
    )
    def test_emits_human_readable_ai_act_planning_failure_details(self):
        pass

    @pytest.mark.skip(
        reason="The Python verbose aiAct renderer consumes a different progress "
        "payload contract; upstream timeline expectations do not map 1:1"
    )
    def test_exports_inline_verbose_dump_screenshots_to_readable_file_paths(self):
        pass

    @pytest.mark.skip(
        reason="The Python verbose aiAct renderer consumes a different progress "
        "payload contract; upstream timeline expectations do not map 1:1"
    )
    def test_emits_jsonl_ai_act_progress_events_while_act_is_running(self):
        pass


async def _await(value):
    return value
