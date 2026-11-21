"""Agent option construction (upstream packages/cli/src/config-factory.ts)."""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from midscene.core.agent.agent_options import AgentOptions


def _build_agent_options(section: dict) -> "AgentOptions":
    from midscene.core.agent.agent_options import AgentOptions

    agent_section = section.get("agent") or {}
    return AgentOptions(
        group_name=agent_section.get("groupName", "Midscene Report"),
        group_description=agent_section.get("groupDescription", ""),
        generate_report=agent_section.get("generateReport", True),
        auto_print_report_msg=agent_section.get("autoPrintReportMsg", True),
        report_file_name=agent_section.get("reportFileName"),
        cache_id=_extract_cache_id(agent_section.get("cache")),
        replanning_cycle_limit=agent_section.get("replanningCycleLimit"),
    )


def _extract_cache_id(cache: object) -> Optional[str]:
    if isinstance(cache, str):
        return cache
    if isinstance(cache, dict):
        return cache.get("id")
    return None
