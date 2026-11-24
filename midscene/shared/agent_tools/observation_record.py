"""Portable UI observation manifests (upstream observation-record.ts).

Records use the upstream camelCase JSON shape so the Python CLI can exchange
manifests with the TypeScript implementation.
"""

import hashlib
import math
import os
import random
import re
import shutil
import string
import time
from pathlib import Path
from typing import Any

from midscene.shared.agent_tools.types import UIObservationFrame, UIObservationRecord
from midscene.shared.env import get_midscene_run_dir

_DATA_URL_PATTERN = re.compile(
    r"^data:image/(png|jpe?g);base64,([\s\S]+)$", re.IGNORECASE
)


def _random_suffix() -> str:
    alphabet = string.digits + string.ascii_lowercase
    return "".join(random.choice(alphabet) for _ in range(8))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fail(location: str, message: str) -> None:
    raise ValueError(f"Invalid UI observation record at {location}: {message}")


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def default_observation_record_path() -> str:
    return str(
        Path(get_midscene_run_dir("output"))
        / f"observation-{_now_ms()}-{_random_suffix()}.json"
    )


def _check_object(value: Any, location: str, allowed: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(location, "Expected object")
    unknown = [key for key in value if key not in allowed]
    if unknown:
        _fail(location, f"Unrecognized key(s) in object: {', '.join(unknown)}")
    return value


def parse_ui_observation_record(input_value: Any) -> UIObservationRecord:
    record = _check_object(
        input_value,
        "record",
        [
            "type",
            "version",
            "startedAt",
            "endedAt",
            "frames",
            "shotSize",
            "shrunkShotToLogicalRatio",
        ],
    )
    if record.get("type") != "midscene_ui_observation":
        _fail("type", "Invalid literal value")
    if record.get("version") != 1:
        _fail("version", "Invalid literal value")

    for key in ("startedAt", "endedAt"):
        value = record.get(key)
        if not _is_finite_number(value) or value < 0:
            _fail(key, "Expected a finite nonnegative number")

    frames = record.get("frames")
    if not isinstance(frames, list) or not frames:
        _fail("frames", "Expected at least 1 frame")
    parsed_frames: list[UIObservationFrame] = []
    for index, frame in enumerate(frames):
        frame_obj = _check_object(
            frame, f"frames.{index}", ["path", "mimeType", "capturedAt"]
        )
        path = frame_obj.get("path")
        if not isinstance(path, str) or not path:
            _fail(f"frames.{index}.path", "Expected a non-empty string")
        mime_type = frame_obj.get("mimeType")
        if mime_type not in ("image/png", "image/jpeg"):
            _fail(f"frames.{index}.mimeType", "Invalid enum value")
        captured_at = frame_obj.get("capturedAt")
        if not _is_finite_number(captured_at) or captured_at < 0:
            _fail(
                f"frames.{index}.capturedAt",
                "Expected a finite nonnegative number",
            )
        parsed_frames.append(
            {
                "path": path,
                "mimeType": mime_type,
                "capturedAt": captured_at,
            }
        )

    shot_size = _check_object(record.get("shotSize"), "shotSize", ["width", "height"])
    for key in ("width", "height"):
        value = shot_size.get(key)
        if not _is_finite_number(value) or value <= 0:
            _fail(f"shotSize.{key}", "Expected a positive finite number")

    ratio = record.get("shrunkShotToLogicalRatio")
    if not _is_finite_number(ratio) or ratio <= 0:
        _fail(
            "shrunkShotToLogicalRatio",
            "Expected a positive finite number",
        )

    if record["endedAt"] < record["startedAt"]:
        _fail("endedAt", "must be greater than or equal to startedAt")

    return {
        "type": "midscene_ui_observation",
        "version": 1,
        "startedAt": record["startedAt"],
        "endedAt": record["endedAt"],
        "frames": parsed_frames,
        "shotSize": {"width": shot_size["width"], "height": shot_size["height"]},
        "shrunkShotToLogicalRatio": ratio,
    }


def clone_ui_observation_record(
    record: UIObservationRecord,
) -> UIObservationRecord:
    """Return a detached record so callers cannot mutate runtime state."""
    return {
        **record,
        "frames": [dict(frame) for frame in record["frames"]],
        "shotSize": dict(record["shotSize"]),
    }


def read_ui_observation_record(file_path: str) -> UIObservationRecord:
    resolved = Path(file_path).resolve()
    try:
        import json

        parsed = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - message mirrors upstream
        raise ValueError(
            f"Failed to read UI observation record {resolved}: {error}"
        ) from error

    record = parse_ui_observation_record(parsed)
    manifest_directory = resolved.parent
    frames: list[UIObservationFrame] = []
    for index, frame in enumerate(record["frames"]):
        frame_path = Path(frame["path"])
        if frame_path.is_absolute():
            _fail(
                f"frames.{index}.path",
                "expected a relative image path",
            )
        image_path = (manifest_directory / frame_path).resolve()
        try:
            relative = image_path.relative_to(manifest_directory)
        except ValueError:
            _fail(
                f"frames.{index}.path",
                "image path escapes the manifest directory",
            )
        del relative
        if not image_path.is_file():
            _fail(
                f"frames.{index}.path",
                f"cannot read image {image_path}: path is not a file",
            )
        frames.append({**frame, "path": str(image_path)})
    return {**record, "frames": frames}


class UIObservationRecordWriter:
    """Incrementally persist frames and export their resolved manifest."""

    def __init__(self, file_path: str | None = None) -> None:
        self.output_path = (
            str(Path(file_path).resolve())
            if file_path
            else default_observation_record_path()
        )
        output = Path(self.output_path)
        self.frames_directory = str(output.parent / f"{output.stem}.frames")
        self._temporary_frames_directory = (
            f"{self.frames_directory}.tmp-{os.getpid()}-{_random_suffix()}"
        )
        self._finalized = False
        self._disposed = False
        self._finalized_record: UIObservationRecord | None = None

    def persist_frame(self, data_url: str, captured_at: int) -> UIObservationFrame:
        if self._disposed:
            raise RuntimeError("UI observation record writer has been disposed")
        if self._finalized:
            raise RuntimeError("UI observation record has already been finalized")
        match = _DATA_URL_PATTERN.match(data_url)
        if not match:
            raise RuntimeError("UI observation frame must be a PNG or JPEG data URL")
        image_format = "png" if match.group(1).lower() == "png" else "jpeg"
        mime_type = "image/png" if image_format == "png" else "image/jpeg"
        import base64

        raw = base64.b64decode(match.group(2))
        if not raw:
            raise RuntimeError("UI observation frame contains no image data")
        digest = hashlib.sha256(raw).hexdigest()
        file_name = f"{digest}.{image_format}"
        Path(self._temporary_frames_directory).mkdir(parents=True, exist_ok=True)
        temporary_path = Path(self._temporary_frames_directory) / file_name
        if not temporary_path.exists():
            temporary_path.write_bytes(raw)
        return {
            "path": f"{Path(self.frames_directory).name}/{file_name}",
            "mimeType": mime_type,
            "capturedAt": captured_at,
        }

    def resolve_frame_path(self, frame: UIObservationFrame) -> str:
        if self._disposed:
            raise RuntimeError("UI observation record writer has been disposed")
        directory = (
            self.frames_directory
            if self._finalized
            else self._temporary_frames_directory
        )
        return str(Path(directory) / Path(frame["path"]).name)

    def prune_frames(self, frames: list[UIObservationFrame]) -> None:
        if self._disposed:
            raise RuntimeError("UI observation record writer has been disposed")
        temporary = Path(self._temporary_frames_directory)
        if self._finalized or not temporary.exists():
            return
        retained = {Path(frame["path"]).name for frame in frames}
        for entry in temporary.iterdir():
            if entry.name not in retained:
                entry.unlink(missing_ok=True)

    def finalize(
        self, frames: list[UIObservationFrame], metadata: dict[str, Any]
    ) -> UIObservationRecord:
        if self._disposed:
            raise RuntimeError("UI observation record writer has been disposed")
        if self._finalized_record is not None:
            return self._finalized_record
        record = parse_ui_observation_record(
            {
                "type": "midscene_ui_observation",
                "version": 1,
                "frames": frames,
                **metadata,
            }
        )
        self.prune_frames(record["frames"])
        output = Path(self.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(self._temporary_frames_directory)
        temporary.mkdir(parents=True, exist_ok=True)
        finalized_directory = Path(self.frames_directory)
        if finalized_directory.exists():
            shutil.rmtree(finalized_directory)
        temporary.rename(finalized_directory)
        self._finalized = True
        self._finalized_record = {
            **record,
            "frames": [
                {**frame, "path": str(output.parent / frame["path"])}
                for frame in record["frames"]
            ],
        }
        return self._finalized_record

    def dispose(self) -> None:
        if self._disposed:
            return
        shutil.rmtree(self._temporary_frames_directory, ignore_errors=True)
        shutil.rmtree(self.frames_directory, ignore_errors=True)
        self._disposed = True
        self._finalized_record = None


def write_ui_observation_record(
    record: UIObservationRecord, file_path: str | None = None
) -> str:
    """Persist a resolved record as a JSON manifest plus an image directory."""
    validated = parse_ui_observation_record(record)
    output_path = (
        str(Path(file_path).resolve())
        if file_path
        else default_observation_record_path()
    )
    output = Path(output_path)
    frames_directory = output.parent / f"{output.stem}.frames"
    temporary_frames = Path(f"{frames_directory}.tmp-{os.getpid()}-{_random_suffix()}")
    temporary_manifest = Path(f"{output_path}.tmp-{os.getpid()}-{_random_suffix()}")
    copied_paths: dict[str, str] = {}

    try:
        temporary_frames.mkdir(parents=True, exist_ok=True)
        frames: list[UIObservationFrame] = []
        for index, frame in enumerate(validated["frames"]):
            source = Path(frame["path"]).resolve()
            if not source.is_file():
                _fail(
                    f"frames.{index}.path",
                    f"cannot read image {source}: path is not a file",
                )
            relative = copied_paths.get(str(source))
            if relative is None:
                image_extension = "png" if frame["mimeType"] == "image/png" else "jpeg"
                file_name = f"{len(copied_paths):04d}.{image_extension}"
                relative = f"{frames_directory.name}/{file_name}"
                shutil.copyfile(source, temporary_frames / file_name)
                copied_paths[str(source)] = relative
            frames.append({**frame, "path": relative})

        serialized = parse_ui_observation_record({**validated, "frames": frames})
        import json

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_manifest.write_text(
            json.dumps(serialized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if frames_directory.exists():
            shutil.rmtree(frames_directory)
        temporary_frames.rename(frames_directory)
        temporary_manifest.replace(output)
        return output_path
    finally:
        shutil.rmtree(temporary_frames, ignore_errors=True)
        temporary_manifest.unlink(missing_ok=True)


__all__ = [
    "UIObservationRecordWriter",
    "clone_ui_observation_record",
    "default_observation_record_path",
    "parse_ui_observation_record",
    "read_ui_observation_record",
    "write_ui_observation_record",
]
