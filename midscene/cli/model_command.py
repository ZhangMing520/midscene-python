"""Model connectivity commands (upstream packages/cli/src/model-command.ts)."""

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from rich.console import Console

from midscene.cli.dotenv_loader import load_dotenv_config
from midscene.cli.siwc_command import run_siwc_command
from midscene.shared.env import get_global_model_config_manager

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
MODEL_VERIFY_SEPARATOR = "────────────────────────────────────────"


def _model_command_usage(command_name: str) -> str:
    return f"""Usage:
  {command_name} model verify

Verify model connectivity and Midscene compatibility for default, locate, planning, and insight models.
Reads .env from the current working directory, overriding shell environment variables.
Shows endpoints, model names, request counts, and per-check results with duration.
Returns exit code 0 on success and 1 on failure.

Options:
  --help, -h  Show this help
"""


def _assert_no_model_verify_options(args: List[str], command_name: str) -> None:
    for arg in args:
        raise ValueError(
            f"Unknown option for {command_name} model verify: {arg}"
        )


def _format_table(headers: List[str], rows: List[List[str]]) -> str:
    widths = [
        max([len(header)] + [len(row[index]) for row in rows])
        for index, header in enumerate(headers)
    ]
    lines = []
    for row in [headers, *rows]:
        line = "  ".join(
            cell.ljust(widths[index]) for index, cell in enumerate(row)
        )
        lines.append(line.rstrip())
    return "\n".join(lines)


def _display_endpoint(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
        if not parts.scheme or not parts.netloc:
            return "(invalid endpoint URL)"
        host = parts.hostname or ""
        netloc = host
        if parts.port:
            netloc = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return "(invalid endpoint URL)"


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _build_chat_completions_url(base_url: Optional[str] = None) -> str:
    normalized = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _build_curl_command(model_config: Dict[str, Any]) -> str:
    payload = {
        "model": model_config.get("modelName"),
        "messages": [{"role": "user", "content": "What is 1+1?"}],
    }
    return "\n".join(
        [
            f"curl -X POST {_shell_single_quote(_build_chat_completions_url(model_config.get('openaiBaseURL')))} \\",
            f"  -H {_shell_single_quote('Authorization: Bearer ' + (model_config.get('openaiApiKey') or ''))} \\",
            f"  -H {_shell_single_quote('Content-Type: application/json')} \\",
            f"  -d {_shell_single_quote(json.dumps(payload, indent=2))}",
        ]
    )


def _build_curl_dedup_key(model_config: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "baseURL": model_config.get("openaiBaseURL") or DEFAULT_OPENAI_BASE_URL,
            "apiKey": model_config.get("openaiApiKey") or "",
            "modelName": model_config.get("modelName"),
        }
    )


def build_model_verify_curl_commands(
    configs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Deduplicate curl commands by base URL, API key, and model name."""
    command_map: Dict[str, Dict[str, Any]] = {}
    for item in configs:
        model_config = item["modelConfig"]
        key = _build_curl_dedup_key(model_config)
        existing = command_map.get(key)
        if existing is not None:
            existing["intents"].append(item["intent"])
            continue
        command_map[key] = {
            "intents": [item["intent"]],
            "curl": _build_curl_command(model_config),
            "usesDefaultBaseURL": not model_config.get("openaiBaseURL"),
        }
    return list(command_map.values())


def _format_model_verify_failure_output(
    message: Optional[str], curl_commands: List[Dict[str, Any]]
) -> str:
    details = (message or "").strip() or "No failure details were generated."
    curl_section = "\n\n".join(
        (
            f"# {', '.join(item['intents'])}"
            + (
                " (base URL not configured; using OpenAI SDK default)"
                if item["usesDefaultBaseURL"]
                else ""
            )
            + f"\n{item['curl']}"
        )
        for item in curl_commands
    )
    return "\n".join(
        [
            "❌ Model verify failed with messages:",
            MODEL_VERIFY_SEPARATOR,
            "",
            details,
            "",
            MODEL_VERIFY_SEPARATOR,
            "Generated curl requests for basic API connectivity:",
            "If the error is a basic connectivity issue, use these requests to test the base URL, API key, and model name directly.",
            "These commands contain your API key. Do not share them publicly.",
            "",
            curl_section,
        ]
    )


def _default_deps(io: Dict[str, Callable[[str], None]]) -> Dict[str, Any]:
    from midscene.core.ai_model.connectivity import run_connectivity_test

    return {
        "loadDotenv": lambda: load_dotenv_config(
            override=True, debug=True, log=io["stdout"]
        ),
        "getModelConfig": lambda intent: get_global_model_config_manager().get_model_config(
            intent
        ),
        "verifyModel": run_connectivity_test,
    }


async def _run_model_verify_command(
    args: List[str],
    deps: Dict[str, Any],
    io: Dict[str, Callable[[str], None]],
    command_name: str,
) -> int:
    try:
        if "--help" in args or "-h" in args:
            io["stdout"](_model_command_usage(command_name))
            return 0

        _assert_no_model_verify_options(args, command_name)
        io["stdout"](
            "Model verify started. This usually completes within 30 seconds."
        )
        deps["loadDotenv"]()
        io["stdout"]("")

        default_model_config = deps["getModelConfig"]("default")
        locate_model_config = deps["getModelConfig"]("locate")
        planning_model_config = deps["getModelConfig"]("planning")
        insight_model_config = deps["getModelConfig"]("insight")
        curl_commands = build_model_verify_curl_commands(
            [
                {"intent": "default", "modelConfig": default_model_config},
                {"intent": "locate", "modelConfig": locate_model_config},
                {"intent": "planning", "modelConfig": planning_model_config},
                {"intent": "insight", "modelConfig": insight_model_config},
            ]
        )

        base_urls: Dict[str, int] = {}
        model_rows = []
        for intent, config, check in (
            ("planning", planning_model_config, "Text response"),
            ("insight", insight_model_config, "Image understanding"),
            ("locate", locate_model_config, "AI locate"),
            ("default", default_model_config, "Text response"),
        ):
            base_url = (config.get("openaiExtraConfig") or {}).get(
                "baseURL"
            ) or config.get("openaiBaseURL")
            endpoint = (
                _display_endpoint(str(base_url)) if base_url else "provider default"
            )
            if endpoint not in base_urls:
                base_urls[endpoint] = len(base_urls) + 1
            model_rows.append(
                [intent, config.get("modelName") or "", check, f"[{base_urls[endpoint]}]"]
            )
        io["stdout"](
            _format_table(
                ["Model role", "Model", "Check", "Endpoint"], model_rows
            )
        )
        io["stdout"]("")
        for endpoint, index in base_urls.items():
            io["stdout"](f"[{index}] Base URL: {endpoint}")
        io["stdout"]("\nRunning 4 checks...\n")

        result = await deps["verifyModel"](
            {
                "defaultModelConfig": default_model_config,
                "locateModelConfig": locate_model_config,
                "planningModelConfig": planning_model_config,
                "insightModelConfig": insight_model_config,
            }
        )

        check_labels = {
            "text": "Text response",
            "vision": "Image understanding",
            "aiLocate": "AI locate",
        }
        checks = result.get("checks") or []
        io["stdout"](
            _format_table(
                ["Model role", "Check", "Result", "Requests", "Time"],
                [
                    [
                        check.get("intent") or "",
                        check_labels.get(check.get("name"), check.get("name") or ""),
                        "PASS" if check.get("passed") else "FAIL",
                        str(check.get("requestCount")),
                        f"{check.get('durationMs')} ms",
                    ]
                    for check in checks
                ],
            )
        )
        request_endpoints: Dict[str, List[str]] = {}
        for check in checks:
            for endpoint in check.get("endpoints") or []:
                display = _display_endpoint(endpoint)
                intents = request_endpoints.setdefault(display, [])
                if check.get("intent") not in intents:
                    intents.append(check.get("intent"))
            if not check.get("passed") and check.get("message"):
                io["stdout"](f"\n{check.get('intent')}: {check['message']}")
        if request_endpoints:
            io["stdout"]("\nRequest endpoints:")
            for endpoint, intents in request_endpoints.items():
                io["stdout"](f"  {', '.join(intents)}: {endpoint}")
        io["stdout"]("")
        passed_checks = len([check for check in checks if check.get("passed")])
        io["stdout"](
            f"Requests sent: {result.get('requestCount')}. Checks: "
            f"{passed_checks} passed, {len(checks) - passed_checks} failed."
        )

        if result.get("passed"):
            io["stdout"]("✅ Model verify passed.")
            return 0

        io["stderr"](
            _format_model_verify_failure_output(result.get("message"), curl_commands)
        )
        return 1
    except Exception as error:
        io["stderr"](
            "\n".join(
                [
                    MODEL_VERIFY_SEPARATOR,
                    "❌ Model verify failed with messages:",
                    "",
                    str(error),
                    MODEL_VERIFY_SEPARATOR,
                ]
            )
        )
        return 1


async def run_model_command(
    raw_args: List[str],
    deps: Optional[Dict[str, Any]] = None,
    io: Optional[Dict[str, Callable[[str], None]]] = None,
    command_name: str = "midscene",
) -> int:
    """Run `midscene model ...` (upstream runModelCommand)."""
    if io is None:
        io = {"stdout": print, "stderr": lambda message: print(message)}

    action = raw_args[1] if len(raw_args) > 1 else None
    rest_args = list(raw_args[2:])

    if action == "siwc":
        load_dotenv_config(override=False, debug=False)
        return await run_siwc_command(rest_args, io)

    def with_siwc_usage(message: str) -> str:
        return message.replace(
            "  midscene model verify\n",
            "  midscene model verify\n"
            "  midscene model siwc <login|refresh> [options]\n",
        )

    shared_io = {
        "stdout": lambda message: io["stdout"](with_siwc_usage(message)),
        "stderr": lambda message: io["stderr"](with_siwc_usage(message)),
    }
    merged_deps = {**_default_deps(io), **(deps or {})}

    if not action or action in ("--help", "-h"):
        shared_io["stdout"](_model_command_usage(command_name))
        return 0

    if action == "verify":
        return await _run_model_verify_command(
            rest_args, merged_deps, shared_io, command_name
        )

    if action == "eval":
        shared_io["stderr"](
            f"{command_name} model eval is not implemented yet. "
            "It is reserved for future model evaluation suites."
        )
        return 1

    shared_io["stderr"](
        f"Unknown {command_name} model command: {action}\n\n"
        f"{_model_command_usage(command_name)}"
    )
    return 1


def run_model_connect(console: Console) -> bool:
    """Run the model connectivity test (text / vision / aiLocate)."""
    from midscene.core.ai_model.connectivity import run_connectivity_test
    from midscene.shared.env import ModelConfigManager

    async def _run():
        manager = ModelConfigManager()
        result = await run_connectivity_test(
            {
                "defaultModelConfig": manager.get_model_config("default"),
                "locateModelConfig": manager.get_model_config("locate"),
                "planningModelConfig": manager.get_model_config("planning"),
                "insightModelConfig": manager.get_model_config("insight"),
            }
        )
        return result

    result = asyncio.run(_run())
    for check in result["checks"]:
        status = "[green]PASS[/green]" if check["passed"] else "[red]FAIL[/red]"
        console.print(
            f"{status} {check['name']} ({check['intent']}) - {check['modelName']} "
            f"({check.get('modelFamily') or 'default'}) - {check['durationMs']}ms"
        )
    if result["passed"]:
        console.print("[green]All connectivity checks passed[/green]")
        return True
    console.print(f"[red]{result.get('message', '')}[/red]")
    return False


def run_model_verify(console: Console) -> bool:
    """Alias of `model connect` (upstream `midscene model verify`)."""
    return run_model_connect(console)
