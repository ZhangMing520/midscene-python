"""Report artifact export (upstream dump/report-artifact-writer.ts).

Exports a directory artifact or single-file report as a standalone HTML file or
an HTML + asset folder, publishing the result atomically.
"""

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from midscene.core.dump.html_utils import (
    DATA_SCREENSHOT_MODE_ATTR,
    anti_escape_script_tag,
    generate_dump_script_tag,
    generate_image_script_tag,
    generate_report_artifact_script_tag,
    generate_test_run_report_script_tag,
    get_base_url_fix_script,
    get_report_tpl,
    stream_inline_report_images,
)
from midscene.core.dump.image_reference import (
    image_ref_file_extension,
    normalize_stored_image_ref,
)
from midscene.core.dump.report_artifact_publication import publish_report_artifact
from midscene.core.dump.report_artifact_reader import (
    _load_report_dump_for_export,
    read_report_artifact_manifest,
    read_report_dump_scripts,
    read_report_runner_dump,
)
from midscene.core.dump.report_artifact_store import (
    ReportArtifactError,
    assert_report_artifact_path,
    parse_report_artifact_manifest,
    write_report_artifact_file,
)
from midscene.core.dump.screenshot_store import (
    parse_base64_image_data_url,
    report_image_file_name,
)


class TestReportImages:
    """Rewrite image references into the final delivery format."""

    def __init__(self, report_path: str | Path, external: bool):
        self.report_path = Path(report_path)
        self.external = external
        self._locations: dict[str, dict[str, Any]] = {}
        self._files: set[str] = set()

    def _reference(self, ref: dict[str, Any], data_uri: str) -> dict[str, Any]:
        known = self._locations.get(ref["id"])
        if known is not None:
            return {**ref, **known}
        if self.external:
            data = base64.b64decode(parse_base64_image_data_url(data_uri)["rawBase64"])
            location = {
                "storage": "file",
                "path": (
                    f"./screenshots/{report_image_file_name(image_ref_file_extension(ref), data)}"
                ),
            }
        else:
            location = {"storage": "inline"}
        self._locations[ref["id"]] = location
        return {**ref, **location}

    def _rewrite(self, serialized: str) -> str:
        return json.dumps(self._replace(json.loads(serialized)), ensure_ascii=False)

    def _replace(self, value: Any) -> Any:
        ref = normalize_stored_image_ref(value)
        if ref is not None:
            known = self._locations.get(ref["id"])
            return {**ref, **known} if known is not None else ref
        if isinstance(value, dict):
            return {key: self._replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._replace(item) for item in value]
        return value

    def _collect(self, serialized: str) -> list[dict[str, Any]]:
        refs: dict[str, dict[str, Any]] = {}

        def visit(value: Any) -> None:
            ref = normalize_stored_image_ref(value)
            if ref is not None:
                if ref.get("storage") == "file":
                    assert_report_artifact_path(ref.get("path"))
                if ref["id"] not in self._locations:
                    refs.setdefault(ref["id"], ref)
                return
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(json.loads(serialized))
        return list(refs.values())

    def _inline_sources(
        self,
        refs: list[dict[str, Any]],
        source_path: str,
        origins: dict[str, str] | None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        sources: dict[str, dict[str, dict[str, Any]]] = {}
        for ref in refs:
            if ref.get("storage") != "inline":
                continue
            source = (origins or {}).get(ref["id"]) or source_path
            sources.setdefault(source, {})[ref["id"]] = ref
        return sources

    def _write_sync(self, ref: dict[str, Any], data: str) -> None:
        target = self._reference(ref, data)
        if target.get("storage") == "file":
            path = target.get("path")
            if path not in self._files:
                destination = self.report_path.parent / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(
                    base64.b64decode(parse_base64_image_data_url(data)["rawBase64"])
                )
                self._files.add(path)
            return
        with open(self.report_path, "a", encoding="utf-8") as handle:
            handle.write(f"{generate_image_script_tag(ref['id'], data)}\n")

    def rewrite_sync(
        self,
        serialized: str,
        source_path: str,
        origins: dict[str, str] | None = None,
    ) -> str:
        refs = self._collect(serialized)
        for ref in refs:
            if ref.get("storage") != "file":
                continue
            source = (origins or {}).get(ref["id"]) or source_path
            data = (Path(source).parent / ref["path"]).read_bytes()
            self._write_sync(
                ref,
                f"data:{ref['mimeType']};base64,{base64.b64encode(data).decode('ascii')}",
            )
        for source, images in self._inline_sources(refs, source_path, origins).items():

            def visit(
                image_id: str,
                data: str,
                _images: dict[str, Any] = images,
            ) -> bool:
                ref = _images.get(image_id)
                if ref is not None:
                    self._write_sync(ref, data)
                    _images.pop(image_id, None)
                return not _images

            stream_inline_report_images(source, visit)
            if images:
                missing = next(iter(images))
                raise ReportArtifactError(f"Missing report image {missing} in {source}")
        return self._rewrite(serialized)

    async def rewrite_async(
        self,
        serialized: str,
        source_path: str,
        origins: dict[str, str] | None = None,
    ) -> str:
        """Async variant of :meth:`rewrite_sync` (upstream rewriteAsync)."""
        return await asyncio.to_thread(
            self.rewrite_sync, serialized, source_path, origins
        )


class ReportArtifactWriter:
    """Final publisher shared by Test, report merging, and conversion."""

    def __init__(
        self,
        entry: str | Path,
        external: bool,
        kind: str,
        report_id: str | None = None,
    ):
        self.entry = Path(entry)
        self.external = external
        self.kind = kind
        self.manifest: dict[str, Any] = {
            "schemaVersion": 1,
            "kind": kind,
            "reportId": report_id or uuid.uuid4().hex,
            "entry": self.entry.name,
            "status": "complete",
            "groups": [],
        }
        self.images = TestReportImages(self.entry, external)

    @property
    def template(self) -> str:
        template = get_report_tpl()
        end = template.rfind("</html>")
        base = template if end < 0 else template[:end]
        return base + (get_base_url_fix_script() if self.external else "")

    def initialize(self) -> None:
        self.entry.parent.mkdir(parents=True, exist_ok=True)
        self.entry.write_text(self.template, encoding="utf-8")

    def initialize_sync(self) -> None:
        self.initialize()

    def _group(self, group_id: str, attributes: dict[str, Any]) -> Path:
        if any(group["id"] == group_id for group in self.manifest["groups"]):
            raise ReportArtifactError(f"Duplicate report group: {group_id}")
        path = f"data/group-{len(self.manifest['groups']) + 1}/1.json"
        self.manifest["groups"].append(
            {
                "id": group_id,
                "status": "complete",
                "attributes": {
                    **attributes,
                    DATA_SCREENSHOT_MODE_ATTR: "directory",
                },
                "dumps": [path],
            }
        )
        return self.entry.parent / path

    def _inline_group(
        self,
        group_id: str,
        attributes: dict[str, Any],
        serialized: str,
    ) -> str:
        return generate_dump_script_tag(
            serialized,
            {
                **attributes,
                "data-group-id": group_id,
                DATA_SCREENSHOT_MODE_ATTR: "inline",
                "data-report-kind": self.manifest["kind"],
            },
        )

    def add_group(
        self,
        group_id: str,
        serialized: str,
        source_path: str,
        attributes: dict[str, Any],
        origins: dict[str, str] | None = None,
    ) -> None:
        rewritten = self.images.rewrite_sync(serialized, source_path, origins)
        if self.external:
            write_report_artifact_file(self._group(group_id, attributes), rewritten)
        else:
            with open(self.entry, "a", encoding="utf-8") as handle:
                handle.write(self._inline_group(group_id, attributes, rewritten))

    def add_group_sync(
        self,
        group_id: str,
        serialized: str,
        source_path: str,
        attributes: dict[str, Any],
        origins: dict[str, str] | None = None,
    ) -> None:
        self.add_group(group_id, serialized, source_path, attributes, origins)

    def _footer(self, runner: dict[str, Any] | None, comment: str) -> str:
        if self.external:
            data = generate_report_artifact_script_tag("report.json")
        elif runner:
            data = generate_test_run_report_script_tag(runner)
        else:
            data = ""
        return f"{data}{comment}\n</html>\n"

    def finish(self, runner: dict[str, Any] | None = None, comment: str = "") -> None:
        if self.external:
            if runner:
                self.manifest["runner"] = "data/runner.json"
                write_report_artifact_file(
                    self.entry.parent / self.manifest["runner"],
                    json.dumps(runner, ensure_ascii=False),
                )
            parse_report_artifact_manifest(self.manifest)
            write_report_artifact_file(
                self.entry.parent / "report.json",
                json.dumps(self.manifest, ensure_ascii=False),
            )
        with open(self.entry, "a", encoding="utf-8") as handle:
            handle.write(self._footer(runner, comment))

    def finish_sync(
        self, runner: dict[str, Any] | None = None, comment: str = ""
    ) -> None:
        self.finish(runner, comment)


def _validate_export_file_name(file_name: str) -> None:
    if (
        not file_name
        or file_name in (".", "..")
        or Path(file_name).name != file_name
        or file_name.endswith(".html")
    ):
        raise ReportArtifactError(
            "Midscene Test reportFileName must be one path segment without "
            f"an extension: {file_name}"
        )


def _parse_group_attributes(open_tag: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for match in re.finditer(r'([^\s=]+)="([^"]*)"', open_tag):
        key, value = match.group(1), match.group(2)
        if key == "type":
            continue
        attributes[key] = unquote(value)
    return attributes


def _dedupe_executions_keep_latest(
    executions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[str, int] = {}
    for index, execution in enumerate(executions):
        if isinstance(execution, dict) and execution.get("id"):
            latest[execution["id"]] = index
    result: list[dict[str, Any]] = []
    for index, execution in enumerate(executions):
        execution_id = execution.get("id") if isinstance(execution, dict) else None
        if execution_id and latest.get(execution_id) != index:
            continue
        result.append(execution)
    return result


def _export_streamed_report_artifact(
    input_path: Path,
    output: Path,
    artifact: Path,
    destination: Path,
    external: bool,
    overwrite: bool,
    report_file_name: str,
) -> str:
    """Export a streaming/directory report through the shared artifact writer."""
    manifest = read_report_artifact_manifest(input_path)
    runner = read_report_runner_dump(input_path)
    groups: dict[str, dict[str, Any]] = {}
    for source in read_report_dump_scripts(input_path):
        attributes = _parse_group_attributes(source["openTag"])
        group_id = attributes.get("data-group-id")
        if not group_id:
            raise ReportArtifactError("Report execution group is missing its ID.")
        content = (
            source["content"]
            if manifest is not None
            else anti_escape_script_tag(source["content"])
        )
        dump = json.loads(content)
        previous = groups.get(group_id)
        if previous is not None:
            dump["executions"] = _dedupe_executions_keep_latest(
                [
                    *(previous["dump"].get("executions") or []),
                    *(dump.get("executions") or []),
                ]
            )
        groups[group_id] = {"dump": dump, "attributes": attributes}

    if not groups and not runner:
        raise ReportArtifactError("No report execution data was found in the input.")

    hint = next(iter(groups.values()), {}).get("attributes", {}).get("data-report-kind")
    if manifest is not None:
        kind = manifest["kind"]
    elif hint in ("agent", "test"):
        kind = hint
    else:
        kind = "test" if runner else "agent"
    report_id = (manifest or {}).get("reportId") or (runner or {}).get("runId")

    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=output, prefix=".report-export-"))
    try:
        writer = ReportArtifactWriter(
            temporary / "index.html", external, kind, report_id
        )
        writer.initialize_sync()
        for group_id, group in groups.items():
            writer.add_group_sync(
                group_id,
                json.dumps(group["dump"], ensure_ascii=False),
                str(input_path),
                group["attributes"],
            )
        writer.finish_sync(runner)
        publish_report_artifact(
            temporary if external else temporary / "index.html",
            artifact if external else destination,
            directory=external,
            overwrite=overwrite,
        )
        return str(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _export_legacy_report_artifact(
    input_path: Path,
    output: Path,
    artifact: Path,
    destination: Path,
    external: bool,
    overwrite: bool,
    report_file_name: str,
) -> str:
    """Export a legacy self-contained ``midscene_report_dump`` report."""
    from midscene.core.dump.screenshot_restoration import _externalize_images
    from midscene.core.report_html_template import render_report_html

    dump = _load_report_dump_for_export(input_path)
    if not dump.get("executions") and not dump.get("runner"):
        raise ReportArtifactError("No report execution data was found in the input.")

    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=output, prefix=".report-export-"))
    try:
        if external:
            external_dump = _externalize_images(
                dump,
                None,
                temporary / "screenshots",
                set(),
                {"counter": 0},
                "report",
            )
            write_report_artifact_file(
                temporary / "index.html",
                render_report_html(external_dump, report_file_name),
            )
            publish_report_artifact(
                temporary, artifact, directory=True, overwrite=overwrite
            )
        else:
            entry = temporary / "index.html"
            write_report_artifact_file(
                entry, render_report_html(dump, report_file_name)
            )
            publish_report_artifact(
                entry, destination, directory=False, overwrite=overwrite
            )
        return str(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def export_report_artifact(
    report_path: str | Path,
    output_dir: str | Path,
    report_file_name: str,
    output_format: str = "single-html",
    overwrite: bool = False,
) -> str:
    """Export a report as a standalone HTML file or an HTML + asset folder.

    Accepts either a directory artifact (``report.json``) or a single-file
    report, validates the destination, then publishes atomically.
    """
    _validate_export_file_name(report_file_name)
    if output_format not in ("single-html", "html-and-external-assets"):
        raise ReportArtifactError(
            "output_format must be 'single-html' or 'html-and-external-assets'"
        )

    input_path = Path(report_path).resolve()
    output = Path(output_dir).resolve()
    external = output_format == "html-and-external-assets"
    artifact = output / report_file_name
    destination = (
        artifact / "index.html" if external else output / (f"{report_file_name}.html")
    )
    if input_path == destination or (
        external and str(input_path).startswith(f"{artifact}{os.sep}")
    ):
        raise ReportArtifactError(
            "Export destination must differ from the input report."
        )
    existing = artifact if external else destination
    if not overwrite and existing.exists():
        raise ReportArtifactError(f"Report artifact already exists: {existing}")

    if read_report_dump_scripts(input_path) or read_report_runner_dump(input_path):
        return _export_streamed_report_artifact(
            input_path,
            output,
            artifact,
            destination,
            external,
            overwrite,
            report_file_name,
        )
    return _export_legacy_report_artifact(
        input_path,
        output,
        artifact,
        destination,
        external,
        overwrite,
        report_file_name,
    )


__all__ = [
    "ReportArtifactWriter",
    "TestReportImages",
    "_validate_export_file_name",
    "export_report_artifact",
]
