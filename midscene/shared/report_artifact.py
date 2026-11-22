"""Directory report artifacts (upstream dump/report-artifact-*.ts, PR1 #3312).

The implementation now lives under `midscene.core.dump`:
  report_artifact_store.py        manifest, atomic file writes, locking, store
  report_artifact_reader.py       read a directory artifact
  report_artifact_writer.py       export an artifact as HTML / HTML + assets
  report_artifact_publication.py  atomic final publication

This module re-exports the original names so existing imports keep working.
"""

from midscene.core.dump.html_utils import REPORT_ARTIFACT_SCRIPT_TYPE
from midscene.core.dump.report_artifact_publication import publish_report_artifact
from midscene.core.dump.report_artifact_reader import read_report_artifact
from midscene.core.dump.report_artifact_store import (
    SCHEMA_VERSION,
    ReportArtifactError,
    ReportArtifactStore,
    assert_report_artifact_path,
    parse_report_artifact_manifest,
    serialize_payload,
    validate_manifest,
    validate_report_id,
    with_report_artifact_lock,
    write_report_artifact_file,
)
from midscene.core.dump.report_artifact_writer import export_report_artifact

# Browser-safe contract for a self-contained directory report.
REPORT_ARTIFACT_SCHEMA_VERSION = SCHEMA_VERSION

__all__ = [
    "REPORT_ARTIFACT_SCHEMA_VERSION",
    "REPORT_ARTIFACT_SCRIPT_TYPE",
    "ReportArtifactError",
    "ReportArtifactStore",
    "SCHEMA_VERSION",
    "assert_report_artifact_path",
    "export_report_artifact",
    "parse_report_artifact_manifest",
    "publish_report_artifact",
    "read_report_artifact",
    "serialize_payload",
    "validate_manifest",
    "validate_report_id",
    "with_report_artifact_lock",
    "write_report_artifact_file",
]
