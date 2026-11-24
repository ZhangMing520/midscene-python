"""Model call event recording (upstream service-caller/model-call-recorder.ts).

Enabled with ``MIDSCENE_RECORD_MODEL_CALL=true``. Events are appended as
JSONL to ``<midscene_run>/model-requests/<iso>-<pid>.jsonl``.
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from midscene.shared.env import get_midscene_run_dir
from midscene.shared.env.basic import get_basic_env_value
from midscene.shared.env.constants import MIDSCENE_RECORD_MODEL_CALL


def is_model_call_recording_enabled() -> bool:
    value = get_basic_env_value(MIDSCENE_RECORD_MODEL_CALL)
    return value in ("true", "1")


class ModelCallRecorder:
    """Serialize JSONL writes so concurrent calls never interleave lines."""

    def __init__(self) -> None:
        self._process_start_time = (
            datetime.now(UTC).isoformat().replace(":", "-").replace(".", "-")
        )
        self._file_path: Path | None = None
        self._write_queue: asyncio.Task | None = None

    def _get_file_path(self) -> Path | None:
        if self._file_path is not None:
            return self._file_path
        if not is_model_call_recording_enabled():
            return None
        try:
            directory = Path(get_midscene_run_dir("model-requests"))
            self._file_path = directory / (
                f"{self._process_start_time}-{os.getpid()}.jsonl"
            )
        except Exception as error:
            logger.warning(f"Failed to initialize model call recorder: {error}")
        return self._file_path

    def _write_event(self, event: dict[str, Any]) -> None:
        file_path = self._get_file_path()
        if file_path is None:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            **event,
        }
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def record(self, event: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Called outside an event loop: write synchronously.
            try:
                self._write_event(event)
            except Exception as error:
                logger.warning(f"Failed to write model call record: {error}")
            return

        previous = self._write_queue

        async def _write() -> None:
            if previous is not None:
                try:
                    await previous
                except Exception:
                    pass
            try:
                self._write_event(event)
            except Exception as error:
                logger.warning(f"Failed to write model call record: {error}")

        self._write_queue = loop.create_task(_write())


model_call_recorder = ModelCallRecorder()


def record_model_call_event(event: dict[str, Any]) -> None:
    model_call_recorder.record(event)


__all__ = [
    "ModelCallRecorder",
    "is_model_call_recording_enabled",
    "model_call_recorder",
    "record_model_call_event",
]
