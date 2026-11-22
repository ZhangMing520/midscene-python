"""Synced from upstream packages/cli/tests/unit-test/model-command.test.ts."""

from unittest.mock import Mock

import pytest

from midscene.cli import model_command as model_module
from midscene.cli.model_command import (
    build_model_verify_curl_commands,
    run_model_command,
)


def create_model_config(**overrides):
    config = {
        "modelName": "gpt-4o",
        "modelFamily": "gpt-5",
        "openaiBaseURL": "https://api.example.com/v1",
        "openaiApiKey": "sk-test",
        "intent": "default",
        "slot": "default",
    }
    config.update(overrides)
    return config


def create_io():
    stdout = []
    stderr = []
    return {
        "stdout": stdout.append,
        "stderr": stderr.append,
        "out": stdout,
        "err": stderr,
    }


@pytest.mark.asyncio
async def test_includes_siwc_in_model_command_help():
    """includes SIWC in model command help"""
    io = create_io()

    assert await run_model_command(["model", "--help"], {}, io) == 0
    assert any(
        "midscene model siwc <login|refresh> [options]" in message
        for message in io["out"]
    )


@pytest.mark.asyncio
async def test_routes_siwc_options_and_output_without_loading_model_configuration(
    monkeypatch,
):
    """routes siwc options and output without loading model configuration"""
    io = create_io()
    load_dotenv_calls = []
    siwc_calls = []

    def fake_load_dotenv(**kwargs):
        load_dotenv_calls.append(kwargs)

    async def fake_siwc(args, siwc_io):
        siwc_calls.append((args, siwc_io))
        return 0

    monkeypatch.setattr(model_module, "load_dotenv_config", fake_load_dotenv)
    monkeypatch.setattr(model_module, "run_siwc_command", fake_siwc)

    deps = {"loadDotenv": Mock(), "getModelConfig": Mock()}

    assert (
        await run_model_command(
            ["model", "siwc", "login", "--no-open", "--port", "1455"], deps, io
        )
        == 0
    )
    assert siwc_calls == [(["login", "--no-open", "--port", "1455"], io)]
    assert load_dotenv_calls == [{"override": False, "debug": False}]
    deps["loadDotenv"].assert_not_called()
    deps["getModelConfig"].assert_not_called()


@pytest.mark.asyncio
async def test_loads_dotenv_for_siwc_refresh_without_requiring_model_configuration(
    monkeypatch,
):
    """loads dotenv for SIWC refresh without requiring model configuration"""
    io = create_io()
    load_dotenv_calls = []
    siwc_calls = []

    def fake_load_dotenv(**kwargs):
        load_dotenv_calls.append(kwargs)

    async def fake_siwc(args, siwc_io):
        siwc_calls.append((args, siwc_io))
        return 0

    monkeypatch.setattr(model_module, "load_dotenv_config", fake_load_dotenv)
    monkeypatch.setattr(model_module, "run_siwc_command", fake_siwc)

    assert await run_model_command(["model", "siwc", "refresh"], {}, io) == 0
    assert load_dotenv_calls == [{"override": False, "debug": False}]
    assert siwc_calls == [(["refresh"], io)]


def test_deduplicates_curl_commands_by_base_url_api_key_and_model_name():
    """deduplicates curl commands by base URL, API key, and model name"""
    commands = build_model_verify_curl_commands(
        [
            {
                "intent": "default",
                "modelConfig": create_model_config(intent="default"),
            },
            {
                "intent": "planning",
                "modelConfig": create_model_config(intent="planning"),
            },
            {
                "intent": "insight",
                "modelConfig": create_model_config(
                    intent="insight", modelName="gpt-4o-mini"
                ),
            },
        ]
    )

    assert len(commands) == 2
    assert commands[0]["intents"] == ["default", "planning"]
    assert (
        "curl -X POST 'https://api.example.com/v1/chat/completions'"
        in commands[0]["curl"]
    )
    assert "-H 'Authorization: Bearer sk-test'" in commands[0]["curl"]
    assert '"model": "gpt-4o"' in commands[0]["curl"]
    assert '"content": "What is 1+1?"' in commands[0]["curl"]
    assert "max_tokens" not in commands[0]["curl"]
    assert commands[1]["intents"] == ["insight"]
    assert '"model": "gpt-4o-mini"' in commands[1]["curl"]


def test_marks_curl_commands_that_use_the_openai_sdk_default_base_url():
    """marks curl commands that use the OpenAI SDK default base URL"""
    commands = build_model_verify_curl_commands(
        [
            {
                "intent": "default",
                "modelConfig": create_model_config(openaiBaseURL=None),
            }
        ]
    )

    assert len(commands) == 1
    assert commands[0]["usesDefaultBaseURL"] is True
    assert (
        "curl -X POST 'https://api.openai.com/v1/chat/completions'"
        in commands[0]["curl"]
    )


@pytest.mark.asyncio
async def test_runs_model_verify_with_model_configs():
    """runs model verify with model configs"""
    io = create_io()
    order = []

    def stdout(message):
        order.append(("stdout", message))
        io["out"].append(message)

    io["stdout"] = stdout

    configs = {
        "default": create_model_config(intent="default", slot="default"),
        "locate": create_model_config(intent="locate", slot="default"),
        "planning": create_model_config(intent="planning", slot="planning"),
        "insight": create_model_config(intent="insight", slot="insight"),
    }
    verify_calls = []

    async def verify_model(payload):
        verify_calls.append(payload)
        return {"checks": [], "requestCount": 0, "passed": True}

    def load_dotenv():
        order.append(("load", None))

    exit_code = await run_model_command(
        ["model", "verify"],
        {
            "loadDotenv": load_dotenv,
            "getModelConfig": lambda intent: configs[intent],
            "verifyModel": verify_model,
        },
        io,
    )

    assert exit_code == 0
    assert order[0][0] == "stdout"
    assert [item[0] for item in order].count("load") == 1
    assert verify_calls == [
        {
            "defaultModelConfig": configs["default"],
            "locateModelConfig": configs["locate"],
            "planningModelConfig": configs["planning"],
            "insightModelConfig": configs["insight"],
        }
    ]
    assert "Model verify started. This usually completes within 30 seconds." in io["out"]
    assert "" in io["out"]
    assert "✅ Model verify passed." in io["out"]


@pytest.mark.asyncio
async def test_loads_dotenv_with_override_enabled_for_model_verify(monkeypatch):
    """loads dotenv with override enabled for model verify"""
    io = create_io()
    default_config = create_model_config(intent="default", slot="default")
    planning_config = create_model_config(intent="planning", slot="planning")
    insight_config = create_model_config(intent="insight", slot="insight")

    class FakeGlobalManager:
        def get_model_config(self, intent):
            return {
                "default": default_config,
                "locate": {**default_config, "intent": "locate"},
                "planning": planning_config,
                "insight": insight_config,
            }[intent]

    monkeypatch.setattr(
        model_module, "get_global_model_config_manager", lambda: FakeGlobalManager()
    )
    load_dotenv_calls = []
    monkeypatch.setattr(
        model_module,
        "load_dotenv_config",
        lambda **kwargs: load_dotenv_calls.append(kwargs),
    )

    async def verify_model(payload):
        return {"checks": [], "requestCount": 0, "passed": True}

    exit_code = await run_model_command(
        ["model", "verify"], {"verifyModel": verify_model}, io
    )

    assert exit_code == 0
    assert load_dotenv_calls == [
        {"override": True, "debug": True, "log": io["stdout"]}
    ]


@pytest.mark.asyncio
async def test_prints_failure_details_and_generated_curl_commands_when_model_verify_fails():
    """prints failure details and generated curl commands when model verify fails"""
    io = create_io()
    configs = {
        "default": create_model_config(
            intent="default",
            slot="default",
            openaiBaseURL="https://api.example.com/v1",
            openaiApiKey="sk-default",
            modelName="gpt-4o",
        ),
        "locate": create_model_config(
            intent="locate",
            slot="locate",
            modelName="locator",
            openaiBaseURL="https://locate.example/v1",
            openaiApiKey="locate-key",
        ),
        "planning": create_model_config(
            intent="planning",
            slot="planning",
            openaiBaseURL="https://api.example.com/v1",
            openaiApiKey="sk-default",
            modelName="gpt-4o",
        ),
        "insight": create_model_config(
            intent="insight",
            slot="insight",
            openaiBaseURL="https://ark.example.com/api/v3",
            openaiApiKey="ark-key",
            modelName="ep-vision",
        ),
    }

    async def verify_model(payload):
        return {
            "checks": [],
            "requestCount": 0,
            "passed": False,
            "message": "[Vision check - ep-vision (insight)]: 404 Not Found",
        }

    exit_code = await run_model_command(
        ["model", "verify"],
        {
            "loadDotenv": lambda: None,
            "getModelConfig": lambda intent: configs[intent],
            "verifyModel": verify_model,
        },
        io,
    )

    assert exit_code == 1
    output = io["err"][0]
    assert "────────────────────────────────────────" in output
    assert "❌ Model verify failed with messages:" in output
    assert "[Vision check - ep-vision (insight)]: 404 Not Found" in output
    assert "Generated curl requests for basic API connectivity:" in output
    assert (
        "If the error is a basic connectivity issue, use these requests to test "
        "the base URL, API key, and model name directly." in output
    )
    assert "These commands contain your API key." in output
    assert "# default, planning" in output
    assert "# insight" in output
    assert "sk-default" in output
    assert "ark-key" in output
    assert "https://locate.example/v1/chat/completions" in output
    assert len(output.split("curl -X POST")) - 1 == 3


@pytest.mark.asyncio
async def test_explains_when_a_generated_curl_command_uses_the_default_base_url():
    """explains when a generated curl command uses the default base URL"""
    io = create_io()
    configs = {
        "default": create_model_config(
            intent="default", slot="default", openaiBaseURL=None
        ),
        "locate": create_model_config(
            intent="locate",
            slot="locate",
            modelName="locator",
            openaiBaseURL="https://locate.example/v1",
            openaiApiKey="locate-key",
        ),
        "planning": create_model_config(
            intent="planning",
            slot="planning",
            openaiBaseURL="https://api.example.com/v1",
        ),
        "insight": create_model_config(
            intent="insight",
            slot="insight",
            openaiBaseURL="https://api.example.com/v1",
        ),
    }

    async def verify_model(payload):
        return {
            "checks": [],
            "requestCount": 0,
            "passed": False,
            "message": "failed",
        }

    await run_model_command(
        ["model", "verify"],
        {
            "loadDotenv": lambda: None,
            "getModelConfig": lambda intent: configs[intent],
            "verifyModel": verify_model,
        },
        io,
    )

    output = io["err"][0]
    assert (
        "# default (base URL not configured; using OpenAI SDK default)" in output
    )
    assert "curl -X POST 'https://api.openai.com/v1/chat/completions'" in output


@pytest.mark.asyncio
async def test_keeps_model_eval_as_a_reserved_placeholder():
    """keeps model eval as a reserved placeholder"""
    io = create_io()

    exit_code = await run_model_command(["model", "eval"], {}, io)

    assert exit_code == 1
    assert io["err"] == [
        "midscene model eval is not implemented yet. "
        "It is reserved for future model evaluation suites."
    ]
