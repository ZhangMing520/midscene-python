"""Agent options (upstream agent/agent-options.ts)."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union


@dataclass
class AgentOptions:
    """Agent configuration options"""
    test_id: Optional[str] = None
    cache_id: Optional[str] = None
    group_name: str = "Midscene Report"
    group_description: str = ""
    generate_report: bool = True
    auto_print_report_msg: bool = True
    ai_action_context: Optional[str] = None
    report_file_name: Optional[str] = None
    # Model configuration. Either an env-style dict (MIDSCENE_MODEL_NAME,
    # MIDSCENE_MODEL_API_KEY, MIDSCENE_MODEL_BASE_URL, MIDSCENE_MODEL_FAMILY,
    # MIDSCENE_PLANNING_MODEL_* ...), or a legacy callable returning such a dict.
    model_config: Optional[Union[Dict[str, str], Callable]] = None
    # Callback fired at the start of each execution task: (tip: str) -> None
    on_task_start_tip: Optional[Callable] = None
    # Override the replanning cycle limit (default: adapter value, 20 standard)
    replanning_cycle_limit: Optional[int] = None
    # Downscale the captured screenshot before sending it to the model
    # (>= 1; coordinates are mapped back afterwards, upstream
    # AgentOpt.screenshotShrinkFactor)
    screenshot_shrink_factor: float = 1.0
    # Cache configuration: False disables, a string is the cache id, a dict is
    # {id, strategy: 'read-only'|'read-write'|'write-only', cacheDir} (upstream
    # AgentOpt.cache)
    cache: Optional[Union[bool, str, Dict[str, Any]]] = None
    # Milliseconds to wait after each executed action (upstream waitAfterAction)
    wait_after_action_ms: int = 300
    # Async callback awaited after each successful action:
    # (context: {'action': dict}) -> None (upstream waitForActionReady)
    wait_for_action_ready: Optional[Callable] = None
    # Default AI context text per API key, seeded into agent.ai_contexts
    # (upstream AgentOpt.aiContexts)
    ai_contexts: Optional[Dict[str, str]] = None
    # Callback receiving each AIUsageInfo (upstream AgentOpt.onLLMUsage)
    on_llm_usage: Optional[Callable] = None
    # Extra attributes merged into the report dump top level
    report_attributes: Optional[Dict[str, Any]] = None
    # Directory that receives a directory report artifact (report.json +
    # data/<reportId>/*.json) on every report flush, in addition to the
    # single-file HTML/JSON report (upstream report artifact store)
    report_artifact_dir: Optional[str] = None
    # Output format hint forwarded to model runtimes (upstream
    # AgentOpt.outputFormat: 'string' | 'object')
    output_format: Optional[Any] = None
    # Custom OpenAI client factory (upstream AgentOpt.createOpenAIClient)
    create_openai_client: Optional[Callable] = None
    # Extra context text used by aiAct only (upstream AgentOpt.aiActContext)
    ai_act_context: Optional[str] = None
    # When False, skip writing the execution dump report file
    # (upstream withAgentDefaults defaults this to false)
    persist_execution_dump: bool = False
    # Use the device-reported time in planning feedback messages (android)
    use_device_time: bool = False
