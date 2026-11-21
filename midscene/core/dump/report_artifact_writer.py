"""Report artifact export (upstream dump/report-artifact-writer.ts).

Exports a directory artifact or single-file report as a standalone HTML file or
an HTML + asset folder, publishing the result atomically.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Union

from midscene.core.dump.report_artifact_publication import publish_report_artifact
from midscene.core.dump.report_artifact_reader import _load_report_dump_for_export
from midscene.core.dump.report_artifact_store import (
    ReportArtifactError,
    write_report_artifact_file,
)


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


def export_report_artifact(
    report_path: Union[str, Path],
    output_dir: Union[str, Path],
    report_file_name: str,
    output_format: str = "single-html",
    overwrite: bool = False,
) -> str:
    """Export a report as a standalone HTML file or an HTML + asset folder.

    Accepts either a directory artifact (``report.json``) or a single-file
    report, validates the destination, then publishes atomically.
    """
    from midscene.core.dump.screenshot_restoration import _externalize_images
    from midscene.core.report_html_template import render_report_html

    _validate_export_file_name(report_file_name)
    if output_format not in ("single-html", "html-and-external-assets"):
        raise ReportArtifactError(
            "output_format must be 'single-html' or 'html-and-external-assets'"
        )

    input_path = Path(report_path).resolve()
    output = Path(output_dir).resolve()
    external = output_format == "html-and-external-assets"
    artifact = output / report_file_name
    destination = artifact / "index.html" if external else output / (
        f"{report_file_name}.html"
    )
    if input_path == destination or (
        external
        and str(input_path).startswith(f"{artifact}{os.sep}")
    ):
        raise ReportArtifactError(
            "Export destination must differ from the input report."
        )
    existing = artifact if external else destination
    if not overwrite and existing.exists():
        raise ReportArtifactError(f"Report artifact already exists: {existing}")

    dump = _load_report_dump_for_export(input_path)
    if not dump.get("executions") and not dump.get("runner"):
        raise ReportArtifactError(
            "No report execution data was found in the input."
        )

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


__all__ = [
    "_validate_export_file_name",
    "export_report_artifact",
]
