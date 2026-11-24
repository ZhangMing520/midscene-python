"""Record log/screenshot entries (upstream agent/record-to-report.ts)."""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from midscene.core.types import UIContext
from midscene.shared.img.transform import normalize_screenshot_base64

if TYPE_CHECKING:
    from midscene.core.dump.report_action_dump import ExecutionDumpBuilder


class ReportAgent(Protocol):
    _last_execution: dict[str, Any] | None

    def _get_report_builder(self) -> ExecutionDumpBuilder: ...

    def _notify_dump_update_listeners(self, execution: dict[str, Any]) -> None: ...

    async def get_context(self) -> UIContext: ...


def normalize_record_to_report_screenshot(
    screenshot: Any,
    index: int,
) -> dict[str, Any]:
    """Validate and normalize one recordToReport screenshot entry."""
    if not screenshot or not isinstance(screenshot.get("base64"), str):
        raise ValueError(
            f"recordToReport: screenshot #{index + 1} must include a base64 string"
        )
    description = screenshot.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError(
            f"recordToReport: screenshot #{index + 1} description must be a string"
        )
    return {
        "base64": normalize_screenshot_base64(
            screenshot["base64"],
            {"label": f"recordToReport: screenshot #{index + 1} base64"},
        ),
        "description": description,
    }


def record_to_report(
    agent: ReportAgent,
    title: str,
    opt: dict[str, Any] | None = None,
) -> None:
    """Append a log/screenshot entry to the report (upstream
    recordToReport). opt: {content?, screenshots?: [{base64, description?}]}."""
    from midscene.core.dump import build_execution_task

    opt = opt or {}
    screenshots = opt.get("screenshots") or []
    if opt.get("screenshot_base64"):
        screenshots = [{"base64": opt["screenshot_base64"]}]
    tasks = [
        build_execution_task(
            "Log",
            "Screenshot" if screenshots else "Log",
            {"title": title, "content": opt.get("content", "")},
            output=screenshots or None,
        )
    ]
    execution = agent._get_report_builder().add_execution(f"Log - {title}", tasks)
    agent._last_execution = execution
    agent._notify_dump_update_listeners(execution)


async def record_error_to_report(
    agent: ReportAgent,
    title: str,
    opt: dict[str, Any] | None = None,
) -> None:
    """Append a failed Log entry to the report (upstream recordErrorToReport).

    opt: {error: BaseException, content?, screenshotBase64?}. When no
    screenshot is supplied the current interface screenshot is captured.
    """
    from midscene.core.dump import build_execution_task

    opt = opt or {}
    error = opt.get("error")
    message = str(error) if error is not None else ""
    error_info: dict[str, Any] = {
        "name": type(error).__name__ if error is not None else "",
        "message": message,
        "stack": "",
    }
    if isinstance(error, BaseException):
        error_info["stack"] = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
    content = opt.get("content") or message
    screenshot = (
        opt.get("screenshotBase64")
        or opt.get("screenshot_base64")
        or opt.get("screenshot")
    )
    if not screenshot:
        try:
            screenshot = getattr(await agent.get_context(), "screenshot_base64", None)
        except Exception as capture_error:  # screenshot is best effort
            logger.debug(f"record_error_to_report screenshot failed: {capture_error}")
    output = [{"base64": screenshot}] if screenshot else None
    tasks = [
        build_execution_task(
            "Log",
            "Error",
            {"content": content},
            status="failed",
            error=error_info,
            errorMessage=message,
            errorStack=error_info["stack"],
            output=output,
        )
    ]
    execution = agent._get_report_builder().add_execution(
        title, tasks, description=content
    )
    agent._last_execution = execution
    agent._notify_dump_update_listeners(execution)
