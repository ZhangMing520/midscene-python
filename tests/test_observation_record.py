"""UI observation records (upstream observation-record.test.ts)."""

import base64
import json
from pathlib import Path

import pytest

from midscene.shared.agent_tools.observation_record import (
    UIObservationRecordWriter,
    read_ui_observation_record,
    write_ui_observation_record,
)


def _data_url(text: str) -> str:
    return f"data:image/png;base64,{base64.b64encode(text.encode()).decode()}"


class TestUIObservationRecordWriter:
    def test_exports_a_file_backed_record_and_writes_a_portable_json_manifest(
        self, tmp_path
    ):
        output_path = tmp_path / "submission-observation.json"
        writer = UIObservationRecordWriter(
            str(tmp_path / "internal-observation.json")
        )
        first = writer.persist_frame(_data_url("same-frame"), 100)
        second = writer.persist_frame(_data_url("same-frame"), 200)

        record = writer.finalize(
            [first, second],
            {
                "startedAt": 50,
                "endedAt": 250,
                "shotSize": {"width": 100, "height": 50},
                "shrunkShotToLogicalRatio": 1,
            },
        )

        assert first["path"] == second["path"]
        assert Path(record["frames"][0]["path"]).is_absolute()
        assert Path(record["frames"][0]["path"]).exists()
        assert write_ui_observation_record(record, str(output_path)) == str(
            output_path
        )

        serialized = json.loads(output_path.read_text(encoding="utf-8"))
        assert serialized["frames"][0] == {
            "path": "submission-observation.frames/0000.png",
            "mimeType": "image/png",
            "capturedAt": 100,
        }
        assert "base64" not in json.dumps(serialized)
        assert not Path(serialized["frames"][0]["path"]).is_absolute()

        resolved = read_ui_observation_record(str(output_path))
        assert Path(resolved["frames"][0]["path"]).is_absolute()
        assert Path(resolved["frames"][0]["path"]).exists()
        assert (
            Path(resolved["frames"][0]["path"]).read_text(encoding="utf-8")
            == "same-frame"
        )

    def test_rejects_missing_absolute_and_escaping_image_paths(self, tmp_path):
        output_path = tmp_path / "record.json"
        base_record = {
            "type": "midscene_ui_observation",
            "version": 1,
            "startedAt": 50,
            "endedAt": 150,
            "shotSize": {"width": 100, "height": 50},
            "shrunkShotToLogicalRatio": 1,
        }

        for path in (
            "record.frames/missing.png",
            str(tmp_path / "absolute.png"),
            "../escaping.png",
        ):
            output_path.write_text(
                json.dumps(
                    {
                        **base_record,
                        "frames": [
                            {
                                "path": path,
                                "mimeType": "image/png",
                                "capturedAt": 100,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with pytest.raises(ValueError, match=r"frames\.0\.path"):
                read_ui_observation_record(str(output_path))

    def test_rejects_non_image_data_urls_before_writing(self, tmp_path):
        writer = UIObservationRecordWriter(str(tmp_path / "record.json"))
        with pytest.raises(RuntimeError, match="PNG or JPEG data URL"):
            writer.persist_frame("not-an-image", 100)

    def test_rejects_an_observation_whose_end_precedes_its_start(self, tmp_path):
        output_path = tmp_path / "record.json"
        output_path.write_text(
            json.dumps(
                {
                    "type": "midscene_ui_observation",
                    "version": 1,
                    "startedAt": 200,
                    "endedAt": 100,
                    "frames": [
                        {
                            "path": "record.frames/frame.png",
                            "mimeType": "image/png",
                            "capturedAt": 100,
                        }
                    ],
                    "shotSize": {"width": 100, "height": 50},
                    "shrunkShotToLogicalRatio": 1,
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="endedAt"):
            read_ui_observation_record(str(output_path))

    def test_keeps_only_files_referenced_by_the_finalized_record(self, tmp_path):
        writer = UIObservationRecordWriter(str(tmp_path / "record.json"))
        frames = [
            writer.persist_frame(_data_url(f"frame-{index}"), index)
            for index in range(12)
        ]

        record = writer.finalize(
            frames[-2:],
            {
                "startedAt": 0,
                "endedAt": 20,
                "shotSize": {"width": 100, "height": 50},
                "shrunkShotToLogicalRatio": 1,
            },
        )

        assert len(record["frames"]) == 2
        assert len(list(Path(writer.frames_directory).iterdir())) == 2

    def test_disposes_temporary_and_finalized_frame_directories(self, tmp_path):
        writer = UIObservationRecordWriter(str(tmp_path / "record.json"))
        frame = writer.persist_frame(_data_url("frame"), 100)
        temporary_frame_path = writer.resolve_frame_path(frame)

        assert Path(temporary_frame_path).exists()
        writer.dispose()
        assert not Path(temporary_frame_path).exists()

        finalized_writer = UIObservationRecordWriter(
            str(tmp_path / "finalized-record.json")
        )
        finalized_frame = finalized_writer.persist_frame(_data_url("frame"), 100)
        finalized_writer.finalize(
            [finalized_frame],
            {
                "startedAt": 50,
                "endedAt": 150,
                "shotSize": {"width": 100, "height": 50},
                "shrunkShotToLogicalRatio": 1,
            },
        )

        assert Path(finalized_writer.frames_directory).exists()
        finalized_writer.dispose()
        assert not Path(finalized_writer.frames_directory).exists()
