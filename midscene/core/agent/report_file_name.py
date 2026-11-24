"""Report file naming (upstream agent/report-file-name.ts)."""

import os

from midscene.core.dump import get_report_file_name


def report_name(
    agent,
) -> str:
    if agent._report_file_name:
        return agent._report_file_name
    name = getattr(agent.options, "report_file_name", None)
    if name:
        name = os.path.basename(name)
        if name.lower().endswith((".json", ".html")):
            name = name.rsplit(".", 1)[0]
    else:
        tag = getattr(agent.options, "test_id", None) or getattr(
            agent.interface_type, "value", agent.interface_type
        )
        name = get_report_file_name(tag)
    agent._report_file_name = name
    return name
