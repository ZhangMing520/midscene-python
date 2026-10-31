"""Execution dump structures aligned with the upstream report format.

Synced from upstream packages/core/src/types.ts:
  IReportActionDump / IExecutionDump / ExecutionTask / ServiceDump /
  AIUsageInfo field names, and the midscene_run directory layout.
"""

import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .ai_model.env_config import get_midscene_run_dir


def new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def new_log_id() -> str:
    return uuid.uuid4().hex


def get_report_file_name(tag: str = "web") -> str:
    """Report file name in the upstream getReportFileName layout:
    `<tag>-<YYYY-MM-DD_HH-mm-ss>-<8 chars>`, tag overridable via
    MIDSCENE_REPORT_TAG_NAME."""
    report_tag = os.environ.get("MIDSCENE_REPORT_TAG_NAME") or tag
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{report_tag}-{timestamp}-{uuid.uuid4().hex[:8]}"


def build_service_dump(
    dump_type: str,
    user_query: Dict[str, Any],
    data: Any,
    task_info: Dict[str, Any],
    matched_element: Optional[List[Dict[str, Any]]] = None,
    error: Optional[str] = None,
    deep_locate: bool = False,
    assertion_pass: Optional[bool] = None,
    assertion_thought: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one ServiceDump entry (one AI service call)."""
    dump: Dict[str, Any] = {
        "logTime": int(time.time() * 1000),
        "type": dump_type,  # 'locate' | 'extract' | 'assert'
        "logId": new_log_id(),
        "userQuery": user_query,
        "data": data,
        "taskInfo": task_info,
    }
    if matched_element:
        dump["matchedElement"] = matched_element
    if deep_locate:
        dump["deepLocate"] = True
    if assertion_pass is not None:
        dump["assertionPass"] = assertion_pass
    if assertion_thought:
        dump["assertionThought"] = assertion_thought
    if error:
        dump["error"] = error
    return dump


class ExecutionDumpBuilder:
    """Accumulate tasks for one execution and serialize in the upstream
    IReportActionDump structure."""

    def __init__(
        self,
        group_name: str = "Midscene Report",
        group_description: str = "",
        model_briefs: Optional[List[Dict[str, Any]]] = None,
        device_type: Optional[str] = None,
        sdk_version: Optional[str] = None,
    ):
        import midscene

        self.dump: Dict[str, Any] = {
            "sdkVersion": sdk_version or midscene.__version__,
            "groupName": group_name,
            "groupDescription": group_description,
            "modelBriefs": model_briefs or [],
            "executions": [],
        }
        if device_type:
            self.dump["deviceType"] = device_type

    def add_execution(
        self,
        name: str,
        tasks: List[Dict[str, Any]],
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        execution: Dict[str, Any] = {
            "id": uuid.uuid4().hex[:8],
            "logTime": int(time.time() * 1000),
            "name": name,
            "tasks": tasks,
        }
        if description:
            execution["description"] = description
        self.dump["executions"].append(execution)
        return execution

    def to_dict(self) -> Dict[str, Any]:
        return self.dump

    def write_to_disk(self, file_name: Optional[str] = None) -> str:
        """Persist as `<midscene_run>/report/<name>.json` (upstream layout)."""
        report_dir = get_midscene_run_dir("report")
        if not file_name:
            file_name = (
                f"report-{time.strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4().hex[:8]}"
            )
        path = Path(report_dir) / f"{file_name}.json"
        try:
            path.write_text(
                __import__("json").dumps(self.dump, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"failed to write execution dump: {e}")
            return ""
        logger.info(f"Midscene - dump file written: {path}")
        return str(path)


def build_execution_task(
    task_type: str,
    sub_type: Optional[str],
    param: Any,
    status: str = "finished",
    **extra: Any,
) -> Dict[str, Any]:
    """Build one ExecutionTask entry (upstream ExecutionTask field names)."""
    task: Dict[str, Any] = {
        "type": task_type,  # 'Planning' | 'Insight' | 'Action Space' | 'Log'
        "taskId": new_task_id(),
        "status": status,  # 'pending'|'running'|'finished'|'failed'|'cancelled'
        "logTime": int(time.time() * 1000),
    }
    if sub_type:
        task["subType"] = sub_type
    task["param"] = param
    task.update(extra)
    return task


__all__ = [
    "build_service_dump",
    "build_execution_task",
    "ExecutionDumpBuilder",
    "get_report_file_name",
    "new_task_id",
]
