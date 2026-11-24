"""Execution dump structures (upstream dump/report-action-dump.ts).

Synced from upstream packages/core/src/types.ts:
  IReportActionDump / IExecutionDump / ExecutionTask / ServiceDump /
  AIUsageInfo field names, and the midscene_run directory layout.
"""

import base64
import contextlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from midscene.core.dump.report_artifact_store import write_report_artifact_file
from midscene.core.dump.screenshot_restoration import restore_image_references
from midscene.core.dump.screenshot_store import (
    ReportImageStore,
    is_base64_image_data_url,
)
from midscene.core.screenshot_item import ScreenshotItem
from midscene.shared.env import get_midscene_run_dir


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
    user_query: dict[str, Any],
    data: Any,
    task_info: dict[str, Any],
    matched_element: list[dict[str, Any]] | None = None,
    error: str | None = None,
    deep_locate: bool = False,
    assertion_pass: bool | None = None,
    assertion_thought: str | None = None,
) -> dict[str, Any]:
    """Build one ServiceDump entry (one AI service call)."""
    dump: dict[str, Any] = {
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
        model_briefs: list[dict[str, Any]] | None = None,
        device_type: str | None = None,
        sdk_version: str | None = None,
    ):
        import midscene

        self.dump: dict[str, Any] = {
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
        tasks: list[dict[str, Any]],
        description: str | None = None,
    ) -> dict[str, Any]:
        execution: dict[str, Any] = {
            "id": uuid.uuid4().hex[:8],
            "logTime": int(time.time() * 1000),
            "name": name,
            "tasks": tasks,
        }
        if description:
            execution["description"] = description
        self.dump["executions"].append(execution)
        return execution

    def to_dict(self) -> dict[str, Any]:
        return self.dump

    def write_to_disk(self, file_name: str | None = None) -> str:
        """Persist as `<midscene_run>/report/<name>.json` (upstream layout)."""
        report_dir = get_midscene_run_dir("report")
        if not file_name:
            file_name = (
                f"report-{time.strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4().hex[:8]}"
            )
        path = Path(report_dir) / f"{file_name}.json"
        try:
            path.write_text(
                json.dumps(self.dump, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"failed to write execution dump: {e}")
            return ""
        logger.info(f"Midscene - dump file written: {path}")
        return str(path)


def build_execution_task(
    task_type: str,
    sub_type: str | None,
    param: Any,
    status: str = "finished",
    **extra: Any,
) -> dict[str, Any]:
    """Build one ExecutionTask entry (upstream ExecutionTask field names)."""
    task: dict[str, Any] = {
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


def _get_page_or_browser_object_name(value: Any) -> str | None:
    """Return ``Page``/``Browser`` for opaque runtime objects, else ``None``."""
    name = type(value).__name__
    return name if name in ("Page", "Browser") else None


def _is_custom_serializable_object(value: Any) -> bool:
    return callable(getattr(value, "to_serializable", None))


def _prepare_for_serialization(value: Any) -> Any:
    """Replacer equivalent for JSON serialization (upstream replacer)."""
    if _get_page_or_browser_object_name(value):
        return f"[{_get_page_or_browser_object_name(value)} object]"
    if ScreenshotItem.is_screenshot_item(value):
        return value.to_serializable()
    if _is_custom_serializable_object(value):
        return value.to_serializable()
    if isinstance(value, dict):
        # screenshotSequence is a transient model input whose frames are not
        # persisted; serializing it would emit dangling screenshot refs.
        return {
            key: _prepare_for_serialization(item)
            for key, item in value.items()
            if key != "screenshotSequence"
        }
    if isinstance(value, list):
        return [_prepare_for_serialization(item) for item in value]
    return value


def _stringify_dump(data: Any, indents: int | None = None) -> str:
    return json.dumps(
        _prepare_for_serialization(data),
        ensure_ascii=False,
        indent=indents,
    )


def _json_default(value: Any) -> Any:
    """Serialize lazily restored screenshots the way JSON.stringify does."""
    if ScreenshotItem.is_screenshot_item(value):
        return value.to_serializable()
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _is_reference_image_descriptor(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("name"), str)
        and isinstance(value.get("url"), str)
    )


def _replace_reference_image_urls(
    value: Any,
    reference_image_refs_by_url: dict[str, Any],
    ancestors: set | None = None,
) -> Any:
    """Clone plain data, replacing descriptor URLs found inside ``images``."""
    if ancestors is None:
        ancestors = set()
    if not isinstance(value, (dict, list)):
        return value
    if _get_page_or_browser_object_name(value) or _is_custom_serializable_object(value):
        return value
    if id(value) in ancestors:
        return value

    ancestors.add(id(value))
    try:
        if isinstance(value, list):
            return [
                _replace_reference_image_urls(
                    item, reference_image_refs_by_url, ancestors
                )
                for item in value
            ]

        result: dict[str, Any] = {}
        for key, nested_value in value.items():
            if key == "images" and isinstance(nested_value, list):
                images: list[Any] = []
                for image in nested_value:
                    transformed = _replace_reference_image_urls(
                        image, reference_image_refs_by_url, ancestors
                    )
                    if not _is_reference_image_descriptor(image):
                        images.append(transformed)
                        continue
                    reference_image_ref = reference_image_refs_by_url.get(image["url"])
                    if not reference_image_ref or not isinstance(transformed, dict):
                        images.append(transformed)
                        continue
                    images.append({**transformed, "url": reference_image_ref})
                result[key] = images
                continue
            result[key] = _replace_reference_image_urls(
                nested_value, reference_image_refs_by_url, ancestors
            )
        return result
    finally:
        ancestors.discard(id(value))


class ExecutionDump:
    """Serialize and deserialize one execution dump (upstream ExecutionDump)."""

    def __init__(
        self,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> None:
        options = options or {}
        self.id = data.get("id")
        self.log_time = data.get("logTime")
        self.name = data.get("name")
        self.description = data.get("description")
        self.tasks = data.get("tasks") or []
        self.ai_act_context = data.get("aiActContext")
        registered = (
            options.get("referenceImageUrls")
            or options.get("reference_image_urls")
            or []
        )
        self.reference_image_urls = list(
            dict.fromkeys(url for url in registered if is_base64_image_data_url(url))
        )

    def serialize(self, indents: int | None = None) -> str:
        return _stringify_dump(self.to_json(), indents)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "logTime": self.log_time,
            "name": self.name,
            "description": self.description,
            "tasks": [
                {**task, "recorder": task.get("recorder") or []} for task in self.tasks
            ],
            "aiActContext": self.ai_act_context,
        }

    @classmethod
    def from_serialized_string(cls, serialized: str) -> "ExecutionDump":
        return cls.from_json(json.loads(serialized))

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ExecutionDump":
        return cls(data)

    def collect_screenshots(self) -> list[ScreenshotItem]:
        screenshots: list[ScreenshotItem] = []
        for task in self.tasks:
            if not isinstance(task, dict):
                continue
            ui_context = task.get("uiContext")
            if isinstance(ui_context, dict) and ScreenshotItem.is_screenshot_item(
                ui_context.get("screenshot")
            ):
                screenshots.append(ui_context["screenshot"])
            for record in task.get("recorder") or []:
                if isinstance(record, dict) and ScreenshotItem.is_screenshot_item(
                    record.get("screenshot")
                ):
                    screenshots.append(record["screenshot"])
        return screenshots

    def get_reference_image_urls(self) -> list[str]:
        return list(self.reference_image_urls)


class ReportActionDump:
    """Serialize and deserialize report action dumps (upstream ReportActionDump)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.sdk_version = data.get("sdkVersion")
        self.group_name = data.get("groupName")
        self.group_description = data.get("groupDescription")
        self.model_briefs = data.get("modelBriefs")
        executions = data.get("executions") or []
        self.executions = [
            execution
            if isinstance(execution, ExecutionDump)
            else ExecutionDump.from_json(execution)
            for execution in executions
        ]
        self.device_type = data.get("deviceType")

    def serialize(self, indents: int | None = None) -> str:
        return _stringify_dump(self.to_json(), indents)

    def serialize_with_reference_images(
        self,
        reference_image_refs_by_url: dict[str, Any],
        indents: int | None = None,
    ) -> str:
        return _stringify_dump(
            _replace_reference_image_urls(self.to_json(), reference_image_refs_by_url),
            indents,
        )

    def serialize_with_inline_screenshots(self, indents: int | None = None) -> str:
        def process_value(obj: Any) -> Any:
            if ScreenshotItem.is_screenshot_item(obj):
                return {"base64": obj.base64, "capturedAt": obj.captured_at}
            if isinstance(obj, list):
                return [process_value(item) for item in obj]
            if isinstance(obj, dict):
                return {
                    key: process_value(item)
                    for key, item in obj.items()
                    if key != "screenshotSequence"
                }
            return obj

        return json.dumps(
            process_value(self.to_json()),
            ensure_ascii=False,
            indent=indents,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "sdkVersion": self.sdk_version,
            "groupName": self.group_name,
            "groupDescription": self.group_description,
            "modelBriefs": self.model_briefs,
            "executions": [execution.to_json() for execution in self.executions],
            "deviceType": self.device_type,
        }

    @classmethod
    def from_serialized_string(cls, serialized: str) -> "ReportActionDump":
        return cls.from_json(json.loads(serialized))

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ReportActionDump":
        return cls(data)

    def collect_all_screenshots(self) -> list[ScreenshotItem]:
        screenshots: list[ScreenshotItem] = []
        for execution in self.executions:
            screenshots.extend(execution.collect_screenshots())
        return screenshots

    def serialize_to_files(self, base_path: str) -> None:
        """Write the dump plus separate screenshot files next to it."""
        screenshots_dir = f"{base_path}.screenshots"
        Path(screenshots_dir).mkdir(parents=True, exist_ok=True)

        for screenshot in self.collect_all_screenshots():
            image_path = Path(screenshots_dir) / (
                f"{screenshot.id}.{screenshot.extension}"
            )
            if image_path.exists():
                continue
            write_report_artifact_file(
                image_path, base64.b64decode(screenshot.raw_base64)
            )

        Path(base_path).write_text(self.serialize(), encoding="utf-8")

    @staticmethod
    def from_files_as_inline_json(base_path: str) -> str:
        """Read a dump plus its companion screenshots and inline the base64."""
        dump_data = json.loads(Path(base_path).read_text(encoding="utf-8"))
        image_store = ReportImageStore(
            mode="directory",
            report_path=base_path,
            screenshots_dir=f"{base_path}.screenshots",
        )
        processed = restore_image_references(dump_data, image_store.load_data_uri)
        return json.dumps(processed, ensure_ascii=False, default=_json_default)

    @staticmethod
    def cleanup_files(base_path: str) -> None:
        for file_path in (base_path, f"{base_path}.screenshots"):
            with contextlib.suppress(Exception):
                path = Path(file_path)
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)

    @staticmethod
    def get_file_paths(base_path: str) -> list[str]:
        return [base_path, f"{base_path}.screenshots"]


# Backward-compatible alias for existing external consumers.
GroupedActionDump = ReportActionDump


__all__ = [
    "ExecutionDump",
    "ExecutionDumpBuilder",
    "GroupedActionDump",
    "ReportActionDump",
    "build_execution_task",
    "build_service_dump",
    "get_report_file_name",
    "new_log_id",
    "new_task_id",
]
