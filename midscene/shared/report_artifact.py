"""Directory report artifacts (upstream dump/report-artifact-*.ts, PR1 #3312).

The implementation now lives under `midscene.core.dump`:
  report_artifact_store.py        manifest, atomic file writes, locking, store
  report_artifact_reader.py       read a directory artifact
  report_artifact_writer.py       export an artifact as HTML / HTML + assets
  report_artifact_publication.py  atomic final publication

This module re-exports the original names so existing imports keep working.
"""

from midscene.core.dump.report_artifact_publication import publish_report_artifact
from midscene.core.dump.report_artifact_reader import read_report_artifact
from midscene.core.dump.report_artifact_store import (
    SCHEMA_VERSION,
    ReportArtifactError,
    ReportArtifactStore,
    serialize_payload,
    validate_manifest,
    validate_report_id,
    with_report_artifact_lock,
    write_report_artifact_file,
)
from midscene.core.dump.report_artifact_writer import export_report_artifact

__all__ = [
    "ReportArtifactError",
    "ReportArtifactStore",
    "SCHEMA_VERSION",
    "export_report_artifact",
    "publish_report_artifact",
    "read_report_artifact",
    "serialize_payload",
    "validate_manifest",
    "validate_report_id",
    "with_report_artifact_lock",
    "write_report_artifact_file",
]
