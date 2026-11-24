"""Report file naming (upstream agent/report-file-name.ts)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, cast

from midscene.core.dump import get_report_file_name
from midscene.shared.types import InterfaceType

if TYPE_CHECKING:
    from midscene.core.agent.agent_options import AgentOptions


class ReportNamingAgent(Protocol):
    _report_file_name: str | None

    @property
    def options(self) -> AgentOptions: ...

    @property
    def interface_type(self) -> InterfaceType: ...


def report_name(agent: ReportNamingAgent) -> str:
    if agent._report_file_name:
        return agent._report_file_name
    name = cast(str | None, getattr(agent.options, "report_file_name", None))
    if name:
        name = os.path.basename(name)
        if name.lower().endswith((".json", ".html")):
            name = name.rsplit(".", 1)[0]
    else:
        tag = cast(
            str,
            getattr(agent.options, "test_id", None)
            or getattr(agent.interface_type, "value", agent.interface_type),
        )
        name = get_report_file_name(tag)
    agent._report_file_name = name
    return name
