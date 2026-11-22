"""Agent option construction (upstream packages/cli/src/config-factory.ts)."""

from typing import TYPE_CHECKING, Any, Dict, Optional

from midscene.web_integration.agent_init_args import get_agent_init_args

if TYPE_CHECKING:
    from midscene.core.agent.agent_options import AgentOptions


def _build_agent_options(section: dict) -> "AgentOptions":
    from midscene.core.agent.agent_options import AgentOptions

    agent_section = section.get("agent") or {}
    init_args = get_agent_init_args(agent_section) or {}

    options: Dict[str, Any] = {
        "group_name": agent_section.get("groupName", "Midscene Report"),
        "group_description": agent_section.get("groupDescription", ""),
        "generate_report": agent_section.get("generateReport", True),
        "auto_print_report_msg": agent_section.get("autoPrintReportMsg", True),
        "report_file_name": agent_section.get("reportFileName"),
        "cache_id": _extract_cache_id(agent_section.get("cache")),
        "replanning_cycle_limit": init_args.get(
            "replanningCycleLimit",
            agent_section.get("replanningCycleLimit"),
        ),
    }
    if "aiContexts" in init_args:
        options["ai_contexts"] = init_args["aiContexts"]
    if "aiActContext" in init_args:
        options["ai_act_context"] = init_args["aiActContext"]
    if "aiActionContext" in init_args:
        options["ai_action_context"] = init_args["aiActionContext"]
    if "waitAfterAction" in init_args:
        options["wait_after_action_ms"] = init_args["waitAfterAction"]
    if "screenshotShrinkFactor" in init_args:
        options["screenshot_shrink_factor"] = init_args["screenshotShrinkFactor"]

    return AgentOptions(**options)


def _extract_cache_id(cache: object) -> Optional[str]:
    if isinstance(cache, str):
        return cache
    if isinstance(cache, dict):
        return cache.get("id")
    return None
