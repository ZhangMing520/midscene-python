"""Directory report artifact reading (upstream dump/report-artifact-reader.ts).

Reads the manifest plus every execution dump of a directory report and can
merge that back into one in-memory dump for export.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from midscene.core.dump.html_utils import (
    extract_report_artifact_path_sync,
    generate_dump_script_tag,
    stream_dump_scripts_sync,
)
from midscene.core.dump.report_artifact_store import (
    ReportArtifactError,
    parse_report_artifact_manifest,
    validate_manifest,
)


def _load_report_dump_for_export(input_path: Path) -> dict[str, Any]:
    """Read a directory artifact or a single-file HTML report into one dump."""
    from midscene.core.dump.report_dump_compactor import (
        _dedupe_executions,
        read_report_dump,
    )
    from midscene.core.dump.screenshot_restoration import _inline_file_images

    if input_path.is_dir() and (input_path / "report.json").exists():
        artifact = read_report_artifact(input_path)
        if not artifact["executions"]:
            raise ReportArtifactError(
                "No report execution data was found in the input."
            )
        dumps = [
            _inline_file_images(
                entry["dump"],
                [input_path / Path(entry["path"]).parent, input_path],
            )
            for entry in artifact["executions"]
        ]
        merged = dict(dumps[0])
        executions: list[dict[str, Any]] = []
        for dump in dumps:
            executions.extend(dump.get("executions") or [])
        merged["executions"] = _dedupe_executions(executions)
        if artifact.get("runner"):
            merged["runner"] = artifact["runner"]
        return merged
    try:
        dump = read_report_dump(str(input_path))
    except ValueError as error:
        raise ReportArtifactError(str(error)) from error
    return cast(dict[str, Any], _inline_file_images(dump, [input_path.parent]))


def read_report_artifact(root: str | Path) -> dict[str, Any]:
    """Read the manifest plus every execution dump of a directory report."""
    base = Path(root)
    manifest_path = base / "report.json"
    if not manifest_path.exists():
        raise ReportArtifactError(f"No report artifact manifest at {manifest_path}")
    manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    executions: list[dict[str, Any]] = []
    for group in manifest["groups"]:
        for dump_path in group["dumps"]:
            executions.append(
                {
                    "group": group["id"],
                    "path": dump_path,
                    "dump": json.loads((base / dump_path).read_text(encoding="utf-8")),
                }
            )
    runner = None
    if manifest.get("runner"):
        runner_path = base / manifest["runner"]
        if runner_path.exists():
            runner = json.loads(runner_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "executions": executions, "runner": runner}


async def read_report_artifact_manifest_async(
    report_path: str | Path,
) -> dict[str, Any] | None:
    """Async counterpart for servers; inline HTML has no manifest."""
    # Python's filesystem helpers are synchronous, so the async entry point
    # shares the exact validation logic instead of duplicating it.
    return read_report_artifact_manifest(report_path)


def read_report_artifact_manifest(
    report_path: str | Path,
) -> dict[str, Any] | None:
    """Read the versioned directory manifest declared by a report entry."""
    entry_path = Path(report_path)
    manifest_path = entry_path.parent / "report.json"
    if not manifest_path.exists() or not entry_path.exists():
        return None
    declared = extract_report_artifact_path_sync(str(entry_path))
    if not declared:
        return None
    manifest = parse_report_artifact_manifest(
        json.loads((entry_path.parent / declared).read_text(encoding="utf-8"))
    )
    if manifest.get("entry") != entry_path.name:
        raise ReportArtifactError("Report entry does not match its artifact manifest")
    return manifest


def stream_report_dump_scripts(
    report_path: str | Path,
    visitor: Callable[[dict[str, str]], bool],
) -> None:
    """Stream inline HTML dumps or external directory dumps one at a time."""
    entry_path = Path(report_path)
    manifest = read_report_artifact_manifest(entry_path)
    if manifest is None:
        stream_dump_scripts_sync(
            str(entry_path),
            lambda dump: visitor(dump) if "data-group-id" in dump["openTag"] else False,
        )
        return
    for group in manifest.get("groups") or []:
        for dump_path in group.get("dumps") or []:
            content = (entry_path.parent / dump_path).read_text(encoding="utf-8")
            json.loads(content)
            tag = generate_dump_script_tag(
                content,
                {"data-group-id": group["id"], **(group.get("attributes") or {})},
            )
            if visitor({"openTag": tag[: tag.index(">") + 1], "content": content}):
                return


def read_report_dump_scripts(
    report_path: str | Path,
) -> list[dict[str, str]]:
    dumps: list[dict[str, str]] = []

    def collect(dump: dict[str, str]) -> bool:
        dumps.append(dump)
        return False

    stream_report_dump_scripts(report_path, collect)
    return dumps


def read_report_runner_dump(
    report_path: str | Path,
) -> dict[str, Any] | None:
    """Read the test-run summary stored next to a report, when present."""
    entry_path = Path(report_path)
    manifest = read_report_artifact_manifest(entry_path)
    if manifest is None:
        from midscene.core.dump.html_utils import TEST_RUN_REPORT_SCRIPT_TYPE

        for content in _iter_script_contents(entry_path):
            tag_end = content.find(">")
            if tag_end == -1:
                continue
            attributes = content[:tag_end]
            if f'type="{TEST_RUN_REPORT_SCRIPT_TYPE}"' not in attributes:
                continue
            from midscene.core.dump.html_utils import anti_escape_script_tag

            parsed = json.loads(anti_escape_script_tag(content[tag_end + 1 :]))
            if (
                parsed.get("schemaVersion") != 1
                or parsed.get("kind") != "test-runner"
                or not isinstance(parsed.get("projects"), list)
            ):
                raise ReportArtifactError(
                    f"Invalid Midscene Test report dump: {entry_path}"
                )
            return cast(dict[str, Any], parsed)
        return None
    runner_path = manifest.get("runner")
    if not runner_path:
        return None
    runner_file = entry_path.parent / runner_path
    if not runner_file.exists():
        return None
    return cast(dict[str, Any], json.loads(runner_file.read_text(encoding="utf-8")))


def _iter_script_contents(entry_path: Path) -> list[str]:
    """Read script bodies once; only used for small summary tags."""
    from midscene.core.dump.html_utils import _iter_tag_contents

    return list(_iter_tag_contents(str(entry_path), "<script", "</script>"))


def read_report_action_dump(report_path: str | Path) -> dict[str, Any]:
    """Read the complete replay, keeping the latest state per execution."""
    entry_path = Path(report_path)
    manifest = read_report_artifact_manifest(entry_path)
    base: dict[str, Any] | None = None
    executions: dict[str, dict[str, Any]] = {}
    anonymous = 0

    def collect(content: str) -> None:
        nonlocal base, anonymous
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("executions"), list
        ):
            raise ReportArtifactError(f"Invalid report execution data: {entry_path}")
        base = parsed
        for execution in parsed["executions"]:
            key = (
                f"id:{execution['id']}"
                if execution.get("id")
                else f"anonymous:{anonymous}"
            )
            if not execution.get("id"):
                anonymous += 1
            executions[key] = execution

    if manifest is not None:
        for group in manifest.get("groups") or []:
            for dump_path in group.get("dumps") or []:
                collect((entry_path.parent / dump_path).read_text(encoding="utf-8"))
    else:
        from midscene.core.dump.html_utils import anti_escape_script_tag

        def visit(dump: dict[str, str]) -> bool:
            collect(anti_escape_script_tag(dump["content"]))
            return False

        stream_dump_scripts_sync(str(entry_path), visit)
    if base is None:
        raise ReportArtifactError(f"No replay dump found in report: {entry_path}")
    return {**base, "executions": list(executions.values())}


__all__ = [
    "_load_report_dump_for_export",
    "read_report_action_dump",
    "read_report_artifact",
    "read_report_artifact_manifest",
    "read_report_artifact_manifest_async",
    "read_report_dump_scripts",
    "read_report_runner_dump",
    "stream_report_dump_scripts",
]
