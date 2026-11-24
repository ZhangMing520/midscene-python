"""Agent options (upstream agent/agent-options.ts)."""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from midscene.core.agent.common import AGENT_AI_CONTEXT_KEYS
from midscene.core.dump.report_session import assert_report_generation_options


@dataclass
class AgentOptions:
    """Agent configuration options"""

    test_id: str | None = None
    cache_id: str | None = None
    group_name: str = "Midscene Report"
    group_description: str = ""
    generate_report: bool = True
    auto_print_report_msg: bool = True
    ai_action_context: str | None = None
    report_file_name: str | None = None
    # Model configuration. Either an env-style dict (MIDSCENE_MODEL_NAME,
    # MIDSCENE_MODEL_API_KEY, MIDSCENE_MODEL_BASE_URL, MIDSCENE_MODEL_FAMILY,
    # MIDSCENE_PLANNING_MODEL_* ...), or a legacy callable returning such a dict.
    model_config: dict[str, str] | Callable | None = None
    # Callback fired at the start of each execution task: (tip: str) -> None
    on_task_start_tip: Callable | None = None
    # Override the replanning cycle limit (default: adapter value, 20 standard)
    replanning_cycle_limit: int | None = None
    # Downscale the captured screenshot before sending it to the model
    # (>= 1; coordinates are mapped back afterwards, upstream
    # AgentOpt.screenshotShrinkFactor)
    screenshot_shrink_factor: float = 1.0
    # Cache configuration: False disables, a string is the cache id, a dict is
    # {id, strategy: 'read-only'|'read-write'|'write-only', cacheDir} (upstream
    # AgentOpt.cache)
    cache: bool | str | dict[str, Any] | None = None
    # Milliseconds to wait after each executed action (upstream waitAfterAction)
    wait_after_action_ms: int = 300
    # Async callback awaited after each successful action:
    # (context: {'action': dict}) -> None (upstream waitForActionReady)
    wait_for_action_ready: Callable | None = None
    # Default AI context text per API key, seeded into agent.ai_contexts
    # (upstream AgentOpt.aiContexts)
    ai_contexts: dict[str, str] | None = None
    # Callback receiving each AIUsageInfo (upstream AgentOpt.onLLMUsage)
    on_llm_usage: Callable | None = None
    # Extra attributes merged into the report dump top level
    report_attributes: dict[str, Any] | None = None
    # Directory that receives a directory report artifact (report.json +
    # data/<reportId>/*.json) on every report flush, in addition to the
    # single-file HTML/JSON report (upstream report artifact store)
    report_artifact_dir: str | None = None
    # Output format hint forwarded to model runtimes (upstream
    # AgentOpt.outputFormat: 'string' | 'object')
    output_format: Any | None = None
    # Custom OpenAI client factory (upstream AgentOpt.createOpenAIClient)
    create_openai_client: Callable | None = None
    # Extra context text used by aiAct only (upstream AgentOpt.aiActContext)
    ai_act_context: str | None = None
    # When False, skip writing the execution dump report file
    # (upstream withAgentDefaults defaults this to false)
    persist_execution_dump: bool = False
    # Use the device-reported time in planning feedback messages (android)
    use_device_time: bool = False


_DEFAULT_OPTIONS = {
    "generateReport": True,
    "persistExecutionDump": False,
    "autoPrintReportMsg": True,
    "groupName": "Midscene Report",
    "groupDescription": "",
}

_SNAKE_DEFAULTS = {
    "generate_report": True,
    "persist_execution_dump": False,
    "auto_print_report_msg": True,
    "group_name": "Midscene Report",
    "group_description": "",
}


def _get_option(options: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(options, dict):
            if key in options:
                return options[key]
        elif hasattr(options, key):
            return getattr(options, key)
    return default


def _set_option(options: Any, key: str, value: Any) -> None:
    if isinstance(options, dict):
        options[key] = value
    else:
        setattr(options, key, value)


def with_agent_defaults(opts: Any = None) -> Any:
    """Return options with the Agent defaults applied (upstream helper)."""
    if opts is None:
        options: Any = AgentOptions()
    elif isinstance(opts, dict):
        options = dict(_DEFAULT_OPTIONS)
        options.update(opts)
    else:
        options = copy.copy(opts)
        for key, value in _SNAKE_DEFAULTS.items():
            if not hasattr(options, key) or getattr(options, key) is None:
                setattr(options, key, value)

    if isinstance(options, dict):
        report_opts = {
            "generateReport": _get_option(options, "generateReport", "generate_report"),
            "persistExecutionDump": _get_option(
                options,
                "persistExecutionDump",
                "persist_execution_dump",
            ),
        }
    else:
        report_opts = {
            "generateReport": _get_option(options, "generate_report", "generateReport"),
            "persistExecutionDump": _get_option(
                options,
                "persist_execution_dump",
                "persistExecutionDump",
            ),
        }
    assert_report_generation_options(report_opts)
    return options


def normalize_agent_options(options: Any, warn: Callable[[str], None]) -> None:
    """Validate and normalize Agent options in place (upstream helper)."""
    ai_contexts = _get_option(options, "aiContexts", "ai_contexts")
    if (
        isinstance(options, dict)
        and ai_contexts is None
        and ("aiContexts" in options or "ai_contexts" in options)
    ):
        raise TypeError("opts.aiContexts must be a plain object")
    if ai_contexts is not None and not isinstance(ai_contexts, dict):
        raise TypeError("opts.aiContexts must be a plain object")

    normalized_contexts: dict[str, Any] = dict(ai_contexts or {})
    for key, value in normalized_contexts.items():
        if key not in AGENT_AI_CONTEXT_KEYS:
            raise TypeError(f"Unknown Agent context key: {key}")
        if value is not None and not isinstance(value, str):
            raise TypeError(f'Agent context "{key}" must be a string')

    ai_act_context = _get_option(options, "aiActContext", "ai_act_context")
    ai_action_context = _get_option(options, "aiActionContext", "ai_action_context")
    deprecated_option = (
        "aiActContext"
        if ai_act_context is not None
        else "aiActionContext"
        if ai_action_context is not None
        else None
    )
    if deprecated_option:
        warn(
            f'Agent option "{deprecated_option}" is deprecated; use '
            '"aiContexts.aiAct" instead. When both are provided, '
            '"aiContexts.aiAct" takes precedence.'
        )

    resolved_ai_act_context = next(
        (
            value
            for value in (
                normalized_contexts.get("aiAct"),
                ai_act_context,
                ai_action_context,
            )
            if value is not None
        ),
        None,
    )
    if resolved_ai_act_context is not None:
        normalized_contexts["aiAct"] = resolved_ai_act_context
    if isinstance(options, dict):
        _set_option(options, "aiContexts", normalized_contexts)
        if resolved_ai_act_context is not None:
            _set_option(options, "aiActContext", resolved_ai_act_context)
            _set_option(options, "aiActionContext", resolved_ai_act_context)
    else:
        _set_option(options, "ai_contexts", normalized_contexts)
        if resolved_ai_act_context is not None:
            _set_option(options, "ai_act_context", resolved_ai_act_context)
            _set_option(options, "ai_action_context", resolved_ai_act_context)

    model_config = _get_option(options, "modelConfig", "model_config")
    if (
        model_config is not None
        and not isinstance(model_config, dict)
        and not callable(model_config)
    ):
        raise TypeError(
            "opts.modelConfig must be a plain object map of env keys to "
            f"values, but got {type(model_config).__name__}"
        )


_AGENT_OPTION_ALIASES = {
    "testId": "test_id",
    "cacheId": "cache_id",
    "groupName": "group_name",
    "groupDescription": "group_description",
    "generateReport": "generate_report",
    "autoPrintReportMsg": "auto_print_report_msg",
    "aiActionContext": "ai_action_context",
    "reportFileName": "report_file_name",
    "modelConfig": "model_config",
    "onTaskStartTip": "on_task_start_tip",
    "replanningCycleLimit": "replanning_cycle_limit",
    "screenshotShrinkFactor": "screenshot_shrink_factor",
    "waitAfterAction": "wait_after_action_ms",
    "waitForActionReady": "wait_for_action_ready",
    "aiContexts": "ai_contexts",
    "onLLMUsage": "on_llm_usage",
    "reportAttributes": "report_attributes",
    "reportArtifactDir": "report_artifact_dir",
    "outputFormat": "output_format",
    "createOpenAIClient": "create_openai_client",
    "aiActContext": "ai_act_context",
    "persistExecutionDump": "persist_execution_dump",
    "useDeviceTime": "use_device_time",
}


def coerce_agent_options(options: Any = None) -> AgentOptions:
    """Convert a dict/AgentOptions pair into AgentOptions.

    Platform factories receive one merged object containing both agent and
    device options (upstream ``AgentOpt & DeviceOpt``); unknown keys such as
    ``androidAdbPath`` or ``wdaHost`` are ignored here.
    """
    if options is None:
        return AgentOptions()
    if isinstance(options, AgentOptions):
        return options
    if isinstance(options, dict):
        fields = AgentOptions.__dataclass_fields__
        kwargs: dict[str, Any] = {}
        for key, value in options.items():
            target = _AGENT_OPTION_ALIASES.get(key, key)
            if target in fields:
                kwargs[target] = value
        return AgentOptions(**kwargs)
    # Custom option objects are normalized in place by the platform factories.
    return cast(AgentOptions, options)


__all__ = [
    "AgentOptions",
    "coerce_agent_options",
    "normalize_agent_options",
    "with_agent_defaults",
]
