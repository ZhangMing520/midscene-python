"""Report artifact publication (upstream dump/report-artifact-publication.ts).

The prepared artifact and destination share a filesystem; lock only the final
publication so unrelated exports do not serialize behind each other.
"""

import hashlib
import os
from pathlib import Path
from typing import Union

from midscene.core.dump.report_artifact_store import (
    ReportArtifactError,
    with_report_artifact_lock,
)


def publish_report_artifact(
    prepared: Union[str, Path],
    destination: Union[str, Path],
    directory: bool = True,
    overwrite: bool = False,
) -> None:
    """Move a prepared artifact into place atomically (upstream publication)."""
    source = Path(prepared)
    target = Path(destination)

    def publish() -> None:
        if target.exists() and not overwrite:
            raise ReportArtifactError(f"Report artifact already exists: {target}")
        if target.is_dir() and overwrite:
            import shutil

            shutil.rmtree(target)
        elif target.exists() and overwrite:
            target.unlink()
        os.replace(source, target)

    # Per-destination lock so unrelated publications in one directory do not
    # serialize behind each other (upstream hashes the destination path).
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:16]
    with_report_artifact_lock(
        target.parent, publish, 10_000, f".report-publish-{digest}.lock"
    )


__all__ = ["publish_report_artifact"]
