"""Report reading, merging, splitting and publishing (upstream core/src/report.ts).

The upstream module is the entry point shared by the Test runner and the
report CLI: it merges Agent reports, removes consumed source artifacts,
splits a report into per-execution dumps and assembles Midscene Test reports.
Image helpers live in `midscene.core.dump.image_reference` and
`midscene.core.dump.screenshot_restoration`; this module re-exports the moved
helpers for existing imports.
"""

import asyncio
import datetime
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import unquote

from loguru import logger

from midscene.core.dump.html_utils import (
    DATA_SCREENSHOT_MODE_ATTR,
    anti_escape_script_tag,
    extract_last_dump_script_sync,
    generate_agent_report_comment,
)
from midscene.core.dump.image_reference import (
    _BASE64_PATTERN,
    _DATA_URI_PATTERN,
    _IMAGE_KEYS,
    _is_image_string,
    normalize_stored_image_ref,
)
from midscene.core.dump.report_action_dump import get_report_file_name
from midscene.core.dump.report_artifact_publication import publish_report_artifact
from midscene.core.dump.report_artifact_reader import (
    _load_report_dump_for_export,
    read_report_artifact,
    read_report_artifact_manifest,
    read_report_dump_scripts,
    read_report_runner_dump,
    stream_report_dump_scripts,
)
from midscene.core.dump.report_artifact_store import ReportArtifactError
from midscene.core.dump.report_artifact_writer import (
    ReportArtifactWriter,
    export_report_artifact,
)
from midscene.core.dump.report_image_export import ReportImageExporter
from midscene.core.dump.screenshot_restoration import (
    _externalize_images,
    _inline_file_images,
    _save_image,
)
from midscene.core.report_html_template import render_report_html
from midscene.core.report_stats import collect_report_summary
from midscene.core.test_run_report import (
    TestRunReportDiagnostic,
    TestRunReportDump,
    TestRunReportSource,
    TestRunReportSourceIndex,
)
from midscene.core.test_runner.reporting.merge_report import (
    MergeTestRunReportSource,
    merge_test_run_report_dumps,
)
from midscene.core.test_runner.reporting.metrics import (
    collect_test_run_report_metrics,
)
from midscene.shared.env import get_midscene_run_dir

_DUMP_HEADER_KEYS = (
    "sdkVersion",
    "groupName",
    "groupDescription",
    "modelBriefs",
    "deviceType",
)

_screenshot_mode_attr_reg_exp = re.compile(
    rf'{DATA_SCREENSHOT_MODE_ATTR}="(inline|directory)"'
)

warned_mismatched_versions: set = set()


def _report_dump_from_string(dump_string: str) -> Dict[str, Any]:
    parsed = json.loads(dump_string)
    if not isinstance(parsed, dict) or not isinstance(
        parsed.get("executions"), list
    ):
        raise ValueError("Invalid report dump")
    return parsed


def dedupe_executions_keep_latest(
    executions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Deduplicate executions by stable id, keeping only the last occurrence."""
    deduped: Dict[str, Dict[str, Any]] = {}
    no_id_counter = 0
    for execution in executions:
        key = execution.get("id") if isinstance(execution, dict) else None
        if not key:
            key = f"__no_id_{no_id_counter}"
            no_id_counter += 1
        deduped[key] = execution
    return list(deduped.values())


def _is_directory_based_report(report_file_path: str) -> bool:
    """Whether the report sits in its own folder (``{name}/index.html``)."""
    return Path(report_file_path).name == "index.html"


def remove_report_artifact(report_file_path: str) -> None:
    """Remove a standalone report or a directory report's whole folder."""
    if _is_directory_based_report(report_file_path):
        shutil.rmtree(Path(report_file_path).parent, ignore_errors=False)
        return
    Path(report_file_path).unlink()


def _read_declared_screenshot_mode(report_file_path: str) -> Optional[str]:
    mode: Optional[str] = None

    def visit(dump_script: Dict[str, str]) -> bool:
        nonlocal mode
        if "data-group-id" not in dump_script["openTag"]:
            return False
        match = _screenshot_mode_attr_reg_exp.search(dump_script["openTag"])
        mode = match.group(1) if match else None
        return True

    try:
        stream_report_dump_scripts(report_file_path, visit)
    except Exception:  # noqa: BLE001 - unreadable files fall back to the caller
        return None
    return mode


def is_directory_mode_report(report_file_path: str) -> bool:
    """Check if a report is in directory mode (html-and-external-assets)."""
    if read_report_artifact_manifest(report_file_path):
        return True
    if Path(report_file_path).name != "index.html":
        return False
    declared = _read_declared_screenshot_mode(report_file_path)
    if declared:
        return declared == "directory"
    return (Path(report_file_path).parent / "screenshots").exists()


def _peek_report_sdk_version(report_file_path: str) -> Optional[str]:
    try:
        reference: Dict[str, Optional[str]] = {"dump": None}

        def visit(dump_script: Dict[str, str]) -> bool:
            reference["dump"] = dump_script["content"]
            return True

        stream_report_dump_scripts(report_file_path, visit)
        dump = reference["dump"] or extract_last_dump_script_sync(
            report_file_path
        )
        if not dump:
            return None
        match = re.search(r'"sdkVersion"\s*:\s*"([^"]+)"', dump)
        return match.group(1) if match else None
    except Exception:  # noqa: BLE001 - a missing version is not an error
        return None


def _try_parse_agent_report_dump(
    dump_string: str,
) -> Optional[Dict[str, Any]]:
    trimmed = dump_string.lstrip()
    if not trimmed.startswith("{") or '"executions"' not in trimmed:
        return None
    try:
        return _report_dump_from_string(trimmed)
    except Exception:  # noqa: BLE001 - mismatched sources are skipped
        return None


def _iso_from_ms(value: float) -> str:
    milliseconds = int(value)
    moment = datetime.datetime.fromtimestamp(
        milliseconds / 1000, tz=datetime.timezone.utc
    )
    return (
        moment.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{milliseconds % 1000:03d}Z"
    )


def _agent_report_timing(
    report: Dict[str, Any], duration_ms: float
) -> Optional[Dict[str, Any]]:
    timing = collect_report_summary(report)["timing"]
    execution_times = [
        execution.get("logTime")
        for execution in report.get("executions") or []
        if isinstance(execution.get("logTime"), (int, float))
        and not isinstance(execution.get("logTime"), bool)
    ]
    started = timing.get("wallTimeStart")
    if started is None and execution_times:
        started = min(execution_times)
    if started is None:
        return None
    fallback_end = started + (
        max(0.0, duration_ms)
        if isinstance(duration_ms, (int, float))
        else 0.0
    )
    ended = timing.get("wallTimeEnd")
    if ended is None:
        ended = max([*execution_times, fallback_end])
    return {
        "startedAt": _iso_from_ms(started),
        "endedAt": _iso_from_ms(ended),
        "durationMs": max(0.0, ended - started),
    }


def merged_agent_report_comment(reports: List[Dict[str, Any]]) -> str:
    if not reports:
        return ""
    if len(reports) == 1:
        return generate_agent_report_comment(reports[0])
    device_types = list(
        dict.fromkeys(
            report.get("deviceType")
            for report in reports
            if report.get("deviceType")
        )
    )
    merged = {
        "sdkVersion": reports[0].get("sdkVersion") or _get_version(),
        "groupName": "Merged Midscene Report",
        "groupDescription": "Agent-readable summary for merged report HTML",
        "modelBriefs": [
            brief
            for report in reports
            for brief in (report.get("modelBriefs") or [])
        ],
        "deviceType": device_types[0] if len(device_types) == 1 else "mixed",
        "executions": dedupe_executions_keep_latest(
            [
                execution
                for report in reports
                for execution in (report.get("executions") or [])
            ]
        ),
    }
    return generate_agent_report_comment(merged)


def _get_version() -> str:
    import midscene

    return midscene.__version__


def validate_test_run_report_file_name(file_name: str) -> None:
    if (
        not file_name
        or file_name in (".", "..")
        or Path(file_name).name != file_name
        or file_name.endswith(".html")
    ):
        raise ValueError(
            "Midscene Test reportFileName must be one path segment without "
            f"an extension: {file_name}"
        )


def write_report_html(
    dump: Dict[str, Any],
    file_name: Optional[str] = None,
    run_dir: Optional[str] = None,
) -> Optional[str]:
    """Write `<midscene_run>/report/<name>.html` rendering the dump."""
    try:
        report_dir = Path(run_dir or get_midscene_run_dir("report"))
        report_dir.mkdir(parents=True, exist_ok=True)
        if not file_name:
            import time as _time

            file_name = (
                f"report-{_time.strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4().hex[:8]}"
            )
        name = (
            file_name.rsplit(".", 1)[0]
            if file_name.lower().endswith((".html", ".json"))
            else file_name
        )
        html = render_report_html(dump, name)
        path = report_dir / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        logger.info(f"Midscene - HTML report written: {path}")
        return str(path)
    except Exception as error:  # noqa: BLE001 - report writing never raises
        logger.warning(f"failed to write HTML report: {error}")
        return None


class ReportMergingTool:
    """Collect report sources and merge them into one report artifact."""

    def __init__(self) -> None:
        self.report_infos: List[Dict[str, Any]] = []

    def create_empty_dump_string(
        self, group_name: str, group_description: Optional[str] = None
    ) -> str:
        dump: Dict[str, Any] = {
            "sdkVersion": "",
            "groupName": group_name,
            "modelBriefs": [],
            "executions": [],
        }
        if group_description is not None:
            dump["groupDescription"] = group_description
        return json.dumps(dump, ensure_ascii=False)

    def append(self, report_info: Dict[str, Any]) -> None:
        attributes = report_info.get("reportAttributes") or {}
        report_file_path = report_info.get("reportFilePath")
        if not report_file_path and attributes.get("testStatus") != "skipped":
            raise ValueError(
                "reportFilePath is required unless reportAttributes.testStatus "
                'is "skipped"'
            )
        if report_file_path:
            source_version = _peek_report_sdk_version(report_file_path)
            current_version = _get_version()
            if (
                source_version
                and current_version
                and source_version != current_version
                and source_version not in warned_mismatched_versions
            ):
                warned_mismatched_versions.add(source_version)
                logger.warning(
                    "[@midscene/core] ReportMergingTool version mismatch: source "
                    f"report was written by @midscene/core@{source_version} but "
                    f"the merger is @midscene/core@{current_version}. Align the "
                    "versions and reinstall."
                )
        self.report_infos.append(report_info)

    def clear(self) -> None:
        self.report_infos = []

    def merge_dump_scripts(
        self, contents: List[str], external: bool
    ) -> str:
        """Merge several dump payloads from one source report into one dump."""
        unescaped = [
            content if external else anti_escape_script_tag(content)
            for content in contents
        ]
        unescaped = [content for content in unescaped if content]
        if not unescaped:
            return ""
        if len(unescaped) == 1:
            return unescaped[0]
        base = _report_dump_from_string(unescaped[0])
        all_executions = list(base.get("executions") or [])
        for content in unescaped[1:]:
            all_executions.extend(
                _report_dump_from_string(content).get("executions") or []
            )
        base["executions"] = dedupe_executions_keep_latest(all_executions)
        return json.dumps(base, ensure_ascii=False)

    def merge_reports(
        self, report_file_name: str = "AUTO", opts: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        opts = opts or {}
        rm_original_reports = bool(opts.get("rmOriginalReports"))
        overwrite = bool(opts.get("overwrite"))
        output_format = opts.get("outputFormat")
        if not self.report_infos:
            logger.info("No reports to merge")
            return None

        runner_dumps = [
            read_report_runner_dump(info["reportFilePath"])
            if info.get("reportFilePath")
            else None
            for info in self.report_infos
        ]
        has_runner_dump = any(runner_dumps)
        external = output_format == "html-and-external-assets"
        name = (
            get_report_file_name("merged-report")
            if report_file_name is None or report_file_name == "AUTO"
            else report_file_name
        )
        validate_test_run_report_file_name(name)
        target_dir = (
            Path(opts["outputDir"]).resolve()
            if opts.get("outputDir")
            else Path(get_midscene_run_dir("report"))
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        artifact = target_dir / name
        output_file_path = (
            artifact / "index.html" if external else Path(f"{artifact}.html")
        )
        if not overwrite and (
            artifact.exists() if external else output_file_path.exists()
        ):
            raise ValueError(
                f"Report file already exists: {output_file_path}\n"
                "Set overwrite to true to overwrite this file."
            )
        if rm_original_reports and any(
            info.get("reportFilePath")
            and _is_directory_based_report(info["reportFilePath"])
            and str(output_file_path).startswith(
                f"{Path(info['reportFilePath']).resolve().parent}{os.sep}"
            )
            for info in self.report_infos
        ):
            raise ValueError(
                "Merged output must be outside source report directories when "
                "removing originals."
            )

        temporary = Path(
            tempfile.mkdtemp(dir=str(target_dir), prefix=".merged-report-")
        )
        entry = temporary / "index.html"
        try:
            writer = ReportArtifactWriter(
                entry, external, "test" if has_runner_dump else "agent"
            )
            writer.initialize_sync()
            agent_reports: List[Dict[str, Any]] = []
            runner_sources: List[MergeTestRunReportSource] = []
            group_ids: set = set()
            for index, info in enumerate(self.report_infos):
                attributes = info.get("reportAttributes") or {}
                serialized = self.create_empty_dump_string(
                    attributes.get("testTitle") or "",
                    attributes.get("testDescription"),
                )
                group_id = f"merged-group-{index}"
                report_file_path = info.get("reportFilePath")
                if report_file_path:
                    dumps = read_report_dump_scripts(report_file_path)
                    original_id = None
                    if dumps:
                        match = re.search(
                            r'data-group-id="([^"]+)"', dumps[0]["openTag"]
                        )
                        original_id = match.group(1) if match else None
                    if (
                        original_id
                        and not has_runner_dump
                        and unquote(original_id) not in group_ids
                    ):
                        group_id = unquote(original_id)
                    if dumps:
                        serialized = self.merge_dump_scripts(
                            [dump["content"] for dump in dumps],
                            bool(
                                read_report_artifact_manifest(report_file_path)
                            ),
                        )
                    else:
                        serialized = (
                            extract_last_dump_script_sync(report_file_path)
                            or serialized
                        )
                if group_id in group_ids:
                    group_id = f"merged-group-{uuid.uuid4().hex}"
                group_ids.add(group_id)
                agent_report = _try_parse_agent_report_dump(serialized)
                if agent_report is not None:
                    agent_reports.append(agent_report)
                if has_runner_dump:
                    runner_sources.append(
                        {
                            "reportId": group_id,
                            "sourcePath": report_file_path
                            or "<skipped-agent-report>",
                            "attributes": attributes,
                            "dump": runner_dumps[index],
                            "timing": (
                                _agent_report_timing(
                                    agent_report,
                                    attributes.get("testDuration") or 0,
                                )
                                if agent_report
                                else None
                            ),
                        }
                    )
                writer.add_group_sync(
                    group_id,
                    serialized,
                    report_file_path or str(entry),
                    {
                        **(
                            {"data-report-id": group_id}
                            if has_runner_dump
                            else {}
                        ),
                        "playwright_test_duration": attributes.get(
                            "testDuration"
                        ),
                        "playwright_test_status": attributes.get("testStatus"),
                        "playwright_test_title": attributes.get("testTitle"),
                        "playwright_test_id": attributes.get("testId"),
                        "playwright_test_description": attributes.get(
                            "testDescription"
                        ),
                        "is_merged": True,
                    },
                )

            runner: Optional[TestRunReportDump] = None
            if has_runner_dump:
                executions = dedupe_executions_keep_latest(
                    [
                        execution
                        for report in agent_reports
                        for execution in (report.get("executions") or [])
                    ]
                )
                metrics = collect_test_run_report_metrics(
                    {"executions": executions}
                )
                execution_metrics = {
                    execution["id"]: collect_test_run_report_metrics(
                        {"executions": [execution]}
                    )
                    for execution in executions
                    if execution.get("id")
                }
                runner = merge_test_run_report_dumps(
                    runner_sources,
                    metrics,
                    uuid.uuid4().hex,
                    execution_metrics,
                )
            writer.finish_sync(runner, merged_agent_report_comment(agent_reports))
            publish_report_artifact(
                temporary if external else entry,
                artifact if external else output_file_path,
                external,
                overwrite,
            )
            if rm_original_reports:
                output_resolved = str(output_file_path.resolve())
                for source_path in dict.fromkeys(
                    str(Path(info["reportFilePath"]).resolve())
                    for info in self.report_infos
                    if info.get("reportFilePath")
                ):
                    if source_path != output_resolved:
                        remove_report_artifact(source_path)
            logger.info(f"Successfully merged new report: {output_file_path}")
            return str(output_file_path)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


def collect_deduped_executions(
    html_path: str,
) -> Dict[str, Any]:
    """Collect executions from a report HTML, keeping the latest by id."""
    base_dump: Optional[Dict[str, Any]] = None
    execution_serial = 0
    latest_serial_by_execution_id: Dict[str, int] = {}

    def record(dump_script: Dict[str, str]) -> bool:
        nonlocal execution_serial
        if "data-group-id" not in dump_script["openTag"]:
            return False
        grouped = _report_dump_from_string(
            anti_escape_script_tag(dump_script["content"])
        )
        for execution in grouped.get("executions") or []:
            execution_serial += 1
            if execution.get("id"):
                latest_serial_by_execution_id[execution["id"]] = execution_serial
        return False

    stream_report_dump_scripts(html_path, record)

    executions: List[Dict[str, Any]] = []
    execution_serial = 0

    def collect(dump_script: Dict[str, str]) -> bool:
        nonlocal base_dump, execution_serial
        if "data-group-id" not in dump_script["openTag"]:
            return False
        grouped = _report_dump_from_string(
            anti_escape_script_tag(dump_script["content"])
        )
        if base_dump is None:
            base_dump = grouped
        for execution in grouped.get("executions") or []:
            execution_serial += 1
            if (
                execution.get("id")
                and latest_serial_by_execution_id.get(execution["id"])
                != execution_serial
            ):
                continue
            executions.append(execution)
        return False

    stream_report_dump_scripts(html_path, collect)
    if base_dump is None:
        raise ValueError(f"No report dump scripts found in {html_path}")
    return {"baseDump": base_dump, "executions": executions}


def _externalize_images_in_execution(
    execution: Dict[str, Any], images: ReportImageExporter
) -> None:
    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        ref = normalize_stored_image_ref(node)
        if ref is not None:
            file_name = images.write(ref)
            node["storage"] = "file"
            node["path"] = f"./screenshots/{file_name}"
            return
        for value in node.values():
            visit(value)

    visit(execution)


def split_report_html_by_execution(options: Dict[str, Any]) -> Dict[str, List[str]]:
    """Reverse parse a report HTML into per-execution JSON files + screenshots."""
    html_path = options["htmlPath"]
    output_dir = Path(options["outputDir"])
    screenshots_dir = output_dir / "screenshots"

    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    execution_json_files: List[str] = []
    images = ReportImageExporter(html_path, str(screenshots_dir))
    collected = collect_deduped_executions(html_path)
    base_dump = collected["baseDump"]

    for file_index, execution in enumerate(collected["executions"], 1):
        _externalize_images_in_execution(execution, images)
        single_dump = {
            key: base_dump[key]
            for key in _DUMP_HEADER_KEYS
            if key in base_dump
        }
        single_dump["executions"] = [execution]
        json_path = output_dir / f"{file_index}.execution.json"
        json_path.write_text(
            json.dumps(single_dump, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        execution_json_files.append(str(json_path))

    return {
        "executionJsonFiles": execution_json_files,
        "screenshotFiles": images.files,
    }


def _unique_test_run_report_sources(
    sources: List[TestRunReportSource],
) -> List[TestRunReportSource]:
    unique: Dict[str, TestRunReportSource] = {}
    for source in sources:
        scope_id = (source.get("scopeId") or "").strip()
        source_path = str(Path(source["sourcePath"]).resolve())
        if not scope_id:
            raise ValueError(
                "Midscene Test report source scopeId must not be empty."
            )
        key = f"{scope_id}\u0000{source.get('dumpPath') or source_path}"
        unique[key] = {**source, "scopeId": scope_id, "sourcePath": source_path}
    return list(unique.values())


def _collect_image_origins(
    dump: Dict[str, Any],
    source: TestRunReportSource,
    origins: Dict[str, str],
) -> None:
    def visit(value: Any) -> None:
        ref = normalize_stored_image_ref(value)
        if ref is not None:
            origins[ref["id"]] = (
                source.get("dumpPath") or source["sourcePath"]
                if ref.get("storage") == "file"
                else source["sourcePath"]
            )
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(dump)


def _prepare_test_run_report_sources(
    sources: List[TestRunReportSource],
    loaded_dumps: Optional[Dict[str, Union[str, Exception]]] = None,
) -> Dict[str, Any]:
    prepared: List[Dict[str, Any]] = []
    diagnostics: List[TestRunReportDiagnostic] = []
    owner_by_scoped_execution: Dict[str, str] = {}
    prepared_by_path: Dict[str, Dict[str, Any]] = {}

    for source_index, source in enumerate(
        _unique_test_run_report_sources(sources)
    ):
        try:
            if source.get("dumpPath"):
                if loaded_dumps is not None and source["dumpPath"] in loaded_dumps:
                    contents = loaded_dumps[source["dumpPath"]]
                else:
                    contents = Path(source["dumpPath"]).read_text(
                        encoding="utf-8"
                    )
                if isinstance(contents, Exception):
                    raise contents
                base_dump = _report_dump_from_string(contents)
                executions = base_dump.get("executions") or []
            else:
                if not Path(source["sourcePath"]).exists():
                    raise ValueError(
                        f"Agent report does not exist: {source['sourcePath']}"
                    )
                source_version = _peek_report_sdk_version(source["sourcePath"])
                current_version = _get_version()
                if (
                    source_version
                    and current_version
                    and source_version != current_version
                    and source_version not in warned_mismatched_versions
                ):
                    warned_mismatched_versions.add(source_version)
                    logger.warning(
                        "[@midscene/core] TestRunReportAssembler version "
                        f"mismatch: source report was written by "
                        f"@midscene/core@{source_version} but the assembler is "
                        f"@midscene/core@{current_version}. Align the workspace "
                        "package versions before generating the Midscene Test "
                        "report."
                    )
                collected = collect_deduped_executions(source["sourcePath"])
                base_dump = collected["baseDump"]
                executions = collected["executions"]
        except Exception as error:  # noqa: BLE001 - diagnostics keep the run alive
            diagnostics.append(
                {
                    "level": "warning",
                    "code": "agent-source-unavailable",
                    "scopeId": source["scopeId"],
                    "sourcePaths": [source["sourcePath"]],
                    "message": (
                        "Agent source could not be collected: "
                        f"{str(error)}"
                    ),
                }
            )
            continue

        image_origins: Dict[str, str] = {}
        _collect_image_origins(base_dump, source, image_origins)
        source_key = source["sourcePath"]
        shared = prepared_by_path.get(source_key)
        if shared is not None:
            shared["imageOrigins"].update(image_origins)
            if source.get("dumpPath"):
                shared["dump"]["executions"] = dedupe_executions_keep_latest(
                    [
                        *(shared["dump"].get("executions") or []),
                        *(base_dump.get("executions") or []),
                    ]
                )
            scoped = next(
                (
                    item
                    for item in prepared
                    if item["reportId"] == shared["reportId"]
                    and item["scopeId"] == source["scopeId"]
                ),
                None,
            )
            execution_ids = list(
                dict.fromkeys(
                    [
                        *(scoped["executionIds"] if scoped else []),
                        *[
                            execution["id"]
                            for execution in executions
                            if execution.get("id")
                        ],
                    ]
                )
            )
            for execution_id in execution_ids:
                key = f"{source['scopeId']}\u0000{execution_id}"
                owner = owner_by_scoped_execution.get(key)
                if owner and owner != shared["reportId"]:
                    raise ValueError(
                        f"Agent execution {execution_id} is present in multiple "
                        f"reports for test scope {source['scopeId']}: {owner}, "
                        f"{shared['reportId']}"
                    )
                owner_by_scoped_execution[key] = shared["reportId"]
            if scoped is not None:
                scoped["executionIds"] = execution_ids
                partial = next(
                    (
                        collection
                        for collection in (
                            scoped.get("collection"),
                            source.get("collection"),
                        )
                        if collection and collection.get("status") == "partial"
                    ),
                    None,
                )
                scoped["collection"] = (
                    partial
                    or source.get("collection")
                    or scoped.get("collection")
                )
            else:
                prepared.append(
                    {
                        **shared,
                        "scopeId": source["scopeId"],
                        "executionIds": execution_ids,
                        "collection": source.get("collection"),
                    }
                )
            continue

        report_id = f"runner-report-{source_index + 1}"
        execution_ids = []
        for execution in executions:
            if not execution.get("id"):
                continue
            key = f"{source['scopeId']}\u0000{execution['id']}"
            previous_owner = owner_by_scoped_execution.get(key)
            if previous_owner and previous_owner != report_id:
                raise ValueError(
                    f"Agent execution {execution['id']} is present in multiple "
                    f"reports for test scope {source['scopeId']}: "
                    f"{previous_owner}, {report_id}"
                )
            owner_by_scoped_execution[key] = report_id
            execution_ids.append(execution["id"])

        dump = {
            "sdkVersion": base_dump.get("sdkVersion"),
            "groupName": base_dump.get("groupName"),
            "groupDescription": base_dump.get("groupDescription"),
            "modelBriefs": base_dump.get("modelBriefs"),
            "deviceType": base_dump.get("deviceType"),
            "executions": executions,
        }
        prepared_source: Dict[str, Any] = {
            "reportId": report_id,
            "scopeId": source["scopeId"],
            "sourcePath": source["sourcePath"],
            "executionIds": execution_ids,
            "collection": source.get("collection"),
            "dump": dump,
            "imageOrigins": image_origins,
        }
        if source.get("dumpPath"):
            prepared_source["dumpPath"] = source["dumpPath"]
        prepared.append(prepared_source)
        prepared_by_path[source_key] = prepared_source

    executions = dedupe_executions_keep_latest(
        [
            execution
            for source in prepared_by_path.values()
            for execution in (source["dump"].get("executions") or [])
        ]
    )
    metrics = collect_test_run_report_metrics({"executions": executions})
    execution_metrics = {
        execution["id"]: collect_test_run_report_metrics(
            {"executions": [execution]}
        )
        for execution in executions
        if execution.get("id")
    }

    collection = dict(metrics.get("collection") or {})
    fields = collection.get("fields") or {}
    adjusted_fields = {
        field: (
            (
                "unknown"
                if not prepared
                else "partial"
                if status == "complete"
                else status
            )
            if diagnostics
            else status
        )
        for field, status in fields.items()
    }
    adjusted_collection = {
        **collection,
        "fields": adjusted_fields,
        "status": (
            ("partial" if prepared else "unknown")
            if diagnostics
            else collection.get("status")
        ),
        "expectedExecutionCount": 0,
        "capturedExecutionCount": 0,
        "reasons": [
            *(collection.get("reasons") or []),
            *(diagnostic.get("message") for diagnostic in diagnostics),
        ],
    }
    return {
        "sources": prepared,
        "diagnostics": diagnostics,
        "capturedMetrics": metrics,
        "executionMetrics": execution_metrics,
        "metrics": {**metrics, "collection": adjusted_collection},
    }


def _build_source_index(prepared: Dict[str, Any]) -> TestRunReportSourceIndex:
    return {
        "sources": [
            {
                "reportId": source["reportId"],
                "scopeId": source["scopeId"],
                "sourcePath": source["sourcePath"],
                "executionIds": source["executionIds"],
                "collection": source.get("collection"),
            }
            for source in prepared["sources"]
        ],
        "metrics": prepared["metrics"],
        "capturedMetrics": prepared["capturedMetrics"],
        "executionMetrics": prepared["executionMetrics"],
        "diagnostics": prepared["diagnostics"],
    }


class TestRunReportAssembler:
    """Build a self-contained Midscene Test report from Agent sources."""

    def _build_runner_dump(
        self,
        options: Dict[str, Any],
        prepared: Dict[str, Any],
    ) -> TestRunReportDump:
        builder = options.get("buildRunnerDump") or options.get(
            "build_runner_dump"
        )
        if builder is None:
            raise ValueError("buildRunnerDump is required")
        return builder(_build_source_index(prepared))

    def _write(
        self,
        options: Dict[str, Any],
        prepared: Dict[str, Any],
        runner_dump: TestRunReportDump,
    ) -> str:
        directory_mode = (
            options.get("outputFormat") == "html-and-external-assets"
        )
        output_dir = Path(options["outputDir"]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        final_artifact_path = output_dir / options["reportFileName"]
        directory_report_path = final_artifact_path / "index.html"
        standalone_report_path = Path(f"{final_artifact_path}.html")
        final_report_path = (
            directory_report_path if directory_mode else standalone_report_path
        )
        existing = (
            [final_artifact_path]
            if directory_mode
            else [standalone_report_path]
        )
        existing = [path for path in existing if path.exists()]
        if existing and not options.get("overwrite"):
            raise ValueError(
                f"Report artifact already exists: {existing[0]}\n"
                "Set overwrite to true to overwrite this report."
            )

        temporary_root = Path(
            tempfile.mkdtemp(dir=str(output_dir), prefix=".test-run-report-")
        )
        temporary_artifact = temporary_root / options["reportFileName"]
        temporary_report = (
            temporary_artifact / "index.html"
            if directory_mode
            else Path(f"{temporary_artifact}.html")
        )
        try:
            if directory_mode:
                temporary_artifact.mkdir(parents=True, exist_ok=True)
            writer = ReportArtifactWriter(
                temporary_report,
                directory_mode,
                "test",
                runner_dump.get("runId"),
            )
            writer.initialize_sync()
            agent_reports: List[Dict[str, Any]] = []
            for source in dict(
                (source["reportId"], source)
                for source in prepared["sources"]
            ).values():
                agent_reports.append(source["dump"])
                writer.add_group_sync(
                    source["reportId"],
                    json.dumps(source["dump"], ensure_ascii=False),
                    source.get("dumpPath") or source["sourcePath"],
                    {
                        "data-report-id": source["reportId"],
                        "data-runner-scope-id": source["scopeId"],
                    },
                    source.get("imageOrigins"),
                )
            writer.finish_sync(
                runner_dump, merged_agent_report_comment(agent_reports)
            )
            publish_report_artifact(
                temporary_artifact if directory_mode else temporary_report,
                final_artifact_path if directory_mode else standalone_report_path,
                directory_mode,
                bool(options.get("overwrite")),
            )
            shutil.rmtree(temporary_root, ignore_errors=True)
            return str(final_report_path)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    def assemble(self, options: Dict[str, Any]) -> str:
        validate_test_run_report_file_name(options["reportFileName"])
        prepared = _prepare_test_run_report_sources(options.get("sources") or [])
        runner_dump = self._build_runner_dump(options, prepared)
        if (
            runner_dump.get("schemaVersion") != 1
            or runner_dump.get("kind") != "test-runner"
        ):
            raise ValueError(
                'buildRunnerDump must return a Midscene Test report dump with '
                'schemaVersion 1 and kind "test-runner".'
            )
        # Validate serializability before creating any output artifact.
        json.dumps(runner_dump)
        return self._write(options, prepared, runner_dump)

    async def assemble_async(self, options: Dict[str, Any]) -> str:
        validate_test_run_report_file_name(options["reportFileName"])
        loaded: Dict[str, Union[str, Exception]] = {}

        async def load(dump_path: str) -> None:
            try:
                loaded[dump_path] = await asyncio.to_thread(
                    Path(dump_path).read_text, encoding="utf-8"
                )
            except Exception as error:  # noqa: BLE001 - reported as a diagnostic
                loaded[dump_path] = error

        await asyncio.gather(
            *[
                load(source["dumpPath"])
                for source in options.get("sources") or []
                if source.get("dumpPath")
            ]
        )
        prepared = _prepare_test_run_report_sources(
            options.get("sources") or [], loaded
        )
        runner_dump = self._build_runner_dump(options, prepared)
        if (
            runner_dump.get("schemaVersion") != 1
            or runner_dump.get("kind") != "test-runner"
        ):
            raise ValueError("Invalid Runner report dump")
        return self._write(options, prepared, runner_dump)


__all__ = [
    "ReportArtifactError",
    "ReportMergingTool",
    "TestRunReportAssembler",
    "_BASE64_PATTERN",
    "_DATA_URI_PATTERN",
    "_IMAGE_KEYS",
    "_externalize_images",
    "_inline_file_images",
    "_is_image_string",
    "_load_report_dump_for_export",
    "_save_image",
    "collect_deduped_executions",
    "dedupe_executions_keep_latest",
    "export_report_artifact",
    "is_directory_mode_report",
    "merged_agent_report_comment",
    "read_report_artifact",
    "read_report_artifact_manifest",
    "read_report_dump_scripts",
    "read_report_runner_dump",
    "remove_report_artifact",
    "split_report_html_by_execution",
    "validate_test_run_report_file_name",
    "write_report_html",
]
