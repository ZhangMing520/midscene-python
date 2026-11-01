"""
Tests for the YAML batch runner (upstream batch-runner / MidsceneYamlConfig).
"""

import json

import pytest

from midscene.core.batch_runner import (
    BatchRunner,
    load_batch_config,
    merge_web_overrides,
    parse_batch_config,
)


class FakePlayer:
    def __init__(self, behavior: str, output_path=None):
        self.behavior = behavior
        self.status = "init"
        self.failed_tasks: list = []
        self.output_path = output_path
        self.result: dict = {}
        self.shared_page = None

    async def run(self):
        if self.behavior == "ok":
            self.status = "done"
        elif self.behavior == "task_fail":
            self.status = "error"
            self.failed_tasks.append({"name": "t", "error": "boom"})
        else:
            self.status = "error"
            raise RuntimeError("player exploded")


def _factory(behaviors: dict):
    def factory(content: str, file_path: str):
        return FakePlayer(behaviors.get(file_path, "ok"))

    return factory


@pytest.fixture
def scripts(tmp_path):
    (tmp_path / "a.yml").write_text("tasks:\n  - name: t\n    flow:\n      - sleep: 1\n")
    (tmp_path / "b.yml").write_text("tasks:\n  - name: t\n    flow:\n      - sleep: 1\n")
    (tmp_path / "c.yml").write_text("tasks:\n  - name: t\n    flow:\n      - sleep: 1\n")
    (tmp_path / "setup.yml").write_text("tasks:\n  - name: t\n    flow:\n      - sleep: 1\n")
    return tmp_path


class TestParseBatchConfig:
    def test_requires_files(self):
        with pytest.raises(ValueError) as exc:
            parse_batch_config({})
        assert '"files" is required' in str(exc.value)

    def test_defaults(self):
        config = parse_batch_config({"files": ["a.yml"]})
        assert config["concurrent"] == 1
        assert config["continueOnError"] is True
        assert config["retry"] == 0

    def test_reuse_page_requires_shared_context_and_concurrent_1(self):
        with pytest.raises(ValueError):
            parse_batch_config({"files": ["a.yml"], "reusePage": True})
        with pytest.raises(ValueError):
            parse_batch_config(
                {"files": ["a.yml"], "reusePage": True, "shareBrowserContext": True,
                 "concurrent": 4}
            )
        ok = parse_batch_config(
            {"files": ["a.yml"], "reusePage": True, "shareBrowserContext": True}
        )
        assert ok["reuse_page"] is True

    def test_negative_retry_rejected(self):
        with pytest.raises(ValueError):
            parse_batch_config({"files": ["a.yml"], "retry": -1})

    def test_load_from_file(self, tmp_path):
        config_file = tmp_path / "midscene.yml"
        config_file.write_text(
            "files:\n  - a.yml\n  - b.yml\nconcurrent: 2\nsummary: out.json\n"
        )
        config = load_batch_config(str(config_file))
        assert config["files"] == ["a.yml", "b.yml"]
        assert config["concurrent"] == 2
        assert config["summary"] == "out.json"


class TestMergeWebOverrides:
    def test_merges_and_preserves_script_keys(self):
        script = {"web": {"url": "https://own.example", "headless": True}}
        merged = merge_web_overrides(script, {"url": "https://batch.example", "userAgent": "UA"})
        assert merged["web"]["url"] == "https://own.example"  # script wins
        assert merged["web"]["userAgent"] == "UA"

    def test_adds_web_section_when_missing(self):
        merged = merge_web_overrides({"tasks": []}, {"url": "https://batch.example"})
        assert merged["web"]["url"] == "https://batch.example"

    def test_native_targets_keep_their_own_env(self):
        for section in ("android", "computer"):
            merged = merge_web_overrides(
                {section: {}, "tasks": []}, {"url": "https://batch.example"}
            )
            assert "web" not in merged
            assert merged[section] == {}


class TestBatchRunner:
    @pytest.mark.asyncio
    async def test_all_success(self, scripts):
        config = {"files": [str(scripts / "a.yml"), str(scripts / "b.yml")]}
        runner = BatchRunner(config, _factory({}))
        results = await runner.run()
        assert [r["resultType"] for r in results] == ["success", "success"]
        assert runner.passed is True

    @pytest.mark.asyncio
    async def test_task_failure_marks_failed(self, scripts):
        behaviors = {str(scripts / "b.yml"): "task_fail"}
        config = {"files": [str(scripts / "a.yml"), str(scripts / "b.yml"), str(scripts / "c.yml")]}
        runner = BatchRunner(config, _factory(behaviors))
        results = await runner.run()
        types = [r["resultType"] for r in results]
        assert types == ["success", "failed", "success"]
        assert "b.yml" in runner.get_failed_files()[0]

    @pytest.mark.asyncio
    async def test_player_exception_marks_failed(self, scripts):
        behaviors = {str(scripts / "a.yml"): "explode"}
        config = {"files": [str(scripts / "a.yml")]}
        runner = BatchRunner(config, _factory(behaviors))
        results = await runner.run()
        assert results[0]["resultType"] == "failed"
        assert "player exploded" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_stop_on_first_failure(self, scripts):
        behaviors = {str(scripts / "a.yml"): "task_fail"}
        config = {"files": [str(scripts / "a.yml"), str(scripts / "b.yml")], "continueOnError": False}
        runner = BatchRunner(config, _factory(behaviors))
        results = await runner.run()
        assert [r["resultType"] for r in results] == ["failed", "notExecuted"]

    @pytest.mark.asyncio
    async def test_retry_repeats_failed_file(self, scripts):
        attempts = {"n": 0}

        class FlakyFactory:
            def __call__(self, content, file_path):
                attempts["n"] += 1
                return FakePlayer("task_fail" if attempts["n"] < 3 else "ok")

        config = {"files": [str(scripts / "a.yml")], "retry": 2}
        runner = BatchRunner(config, FlakyFactory())
        results = await runner.run()
        assert results[0]["resultType"] == "success"
        assert len(results[0]["attempts"]) == 3

    @pytest.mark.asyncio
    async def test_setup_failure_aborts_batch(self, scripts):
        behaviors = {str(scripts / "setup.yml"): "task_fail"}
        config = {"files": [str(scripts / "a.yml"), str(scripts / "b.yml")], "setup": str(scripts / "setup.yml")}
        runner = BatchRunner(config, _factory(behaviors))
        results = await runner.run()
        assert results[0]["resultType"] == "failed"
        assert [r["resultType"] for r in results[1:]] == ["notExecuted", "notExecuted"]

    @pytest.mark.asyncio
    async def test_setup_success_runs_first(self, scripts):
        config = {"files": [str(scripts / "a.yml")], "setup": str(scripts / "setup.yml")}
        runner = BatchRunner(config, _factory({}))
        results = await runner.run()
        assert [r["resultType"] for r in results] == ["success", "success"]

    @pytest.mark.asyncio
    async def test_concurrent_execution(self, scripts):
        config = {"files": [str(scripts / "a.yml"), str(scripts / "b.yml"), str(scripts / "c.yml")], "concurrent": 3}
        runner = BatchRunner(config, _factory({}))
        results = await runner.run()
        assert len(results) == 3
        assert all(r["success"] for r in results)

    @pytest.mark.asyncio
    async def test_summary_written(self, scripts, tmp_path):
        summary = tmp_path / "summary.json"
        config = {"files": [str(scripts / "a.yml")], "summary": str(summary)}
        runner = BatchRunner(config, _factory({}))
        await runner.run()
        data = json.loads(summary.read_text())
        assert data[0]["resultType"] == "success"
        assert "_shared_page" not in data[0]

    @pytest.mark.asyncio
    async def test_web_overrides_applied_to_scripts_without_web(self, scripts):
        captured = {}

        def factory(content, file_path):
            captured[file_path] = content
            return FakePlayer("ok")

        config = {
            "files": [str(scripts / "a.yml")],
            "web": {"url": "https://batch.example", "headless": True},
        }
        await BatchRunner(config, factory).run()
        content = captured[str(scripts / "a.yml")]
        assert "https://batch.example" in content

    def test_web_overrides_not_applied_to_android_scripts(self, scripts):
        content = "android:\n  deviceId: x\ntasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
        runner = BatchRunner({"files": ["x.yml"]}, lambda c, f: FakePlayer("ok"))
        assert runner._apply_web_overrides(content, {"url": "https://x"}) == content

    def test_web_overrides_not_applied_to_desktop_scripts(self, scripts):
        content = "computer: {}\ntasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
        runner = BatchRunner({"files": ["x.yml"]}, lambda c, f: FakePlayer("ok"))
        assert runner._apply_web_overrides(content, {"url": "https://x"}) == content
