"""Synced from upstream packages/core/tests/unit-test/service-caller/model-call-recorder.test.ts.

The Python recorder writes in a node-like process only; upstream's browser and
worker runtime branches have no Python counterpart, so that parametrized case
is skipped. File/JSONL and failure-tolerance behavior is ported directly.
"""

import builtins
import json
import os
import re

import pytest

from midscene.core.ai_model.service_caller.model_call_recorder import ModelCallRecorder


@pytest.mark.asyncio
async def test_does_not_create_a_record_directory_when_recording_is_disabled(
    tmp_path, monkeypatch
):
    """does not create a record directory when recording is disabled"""
    monkeypatch.delenv("MIDSCENE_RECORD_MODEL_CALL", raising=False)
    run_dir = tmp_path / "run"
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    recorder = ModelCallRecorder()

    recorder.record({"type": "request"})

    assert (run_dir / "model-requests").exists() is False


@pytest.mark.asyncio
async def test_uses_one_jsonl_file_when_its_first_events_are_concurrent(
    tmp_path, monkeypatch
):
    """uses one JSONL file when its first events are concurrent"""
    monkeypatch.setenv("MIDSCENE_RECORD_MODEL_CALL", "true")
    run_dir = tmp_path / "run"
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    recorder = ModelCallRecorder()

    for index in range(4):
        recorder.record({"type": "request", "index": index})
    while recorder._write_queue is not None:
        task = recorder._write_queue
        await task
        if recorder._write_queue is task:
            break

    record_dir = run_dir / "model-requests"
    files = list(record_dir.iterdir())
    assert len(files) == 1
    assert re.search(rf"-{os.getpid()}\.jsonl$", files[0].name)

    content = files[0].read_text(encoding="utf-8")
    indexes = [json.loads(line)["index"] for line in content.strip().split("\n")]
    assert indexes == [0, 1, 2, 3]


@pytest.mark.skip(
    reason="Python recorder has no browser/worker runtime branch; it always "
    "uses the filesystem behavior"
)
@pytest.mark.parametrize("runtime", ["browser", "worker"])
@pytest.mark.asyncio
async def test_does_not_record_in_a_runtime(runtime):
    """does not record in a %s runtime"""
    pass


@pytest.mark.asyncio
async def test_continues_recording_after_a_write_failure(tmp_path, monkeypatch):
    """continues recording after a write failure"""
    monkeypatch.setenv("MIDSCENE_RECORD_MODEL_CALL", "true")
    run_dir = tmp_path / "run"
    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    (run_dir / "model-requests").mkdir(parents=True)

    real_open = builtins.open
    attempts = {"count": 0}

    def flaky_open(file, *args, **kwargs):
        if str(file).endswith(".jsonl"):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OSError("disk is full")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)
    recorder = ModelCallRecorder()

    assert recorder.record({"type": "request", "index": 1}) is None
    await recorder._write_queue
    assert recorder.record({"type": "request", "index": 2}) is None
    await recorder._write_queue

    assert attempts["count"] == 2
