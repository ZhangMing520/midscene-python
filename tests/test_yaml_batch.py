"""Rstest YAML batch wrapper (upstream framework/yaml-batch.test.ts).

The rstest wrapper (``runYamlBatchInRstest``) and its result-file plumbing are
Node-only. The case-id aware executor is ported as
``run_yaml_batch_with_case_ids`` and covered below.
"""

import asyncio

import pytest

from midscene.cli.yaml_batch_executor import run_yaml_batch_with_case_ids

_SKIP = (
    "The rstest wrapper and its per-target result files are Node-only; "
    "run_yaml_batch_with_case_ids is covered by TestRunYamlBatchWithCaseIds"
)


class FakePlayer:
    def __init__(self):
        self.status = "init"
        self.failed_tasks = []
        self.output_path = None
        self.result = {}

    async def run(self):
        self.status = "done"


def _scripts(tmp_path, names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_text("tasks:\n  - name: task\n    flow:\n      - sleep: 1\n")
        paths.append(str(path))
    return paths


def _factory(_content, _path):
    return FakePlayer()


class TestRunYamlBatchWithCaseIds:
    def test_pairs_results_with_the_supplied_case_ids(self, tmp_path):
        files = _scripts(tmp_path, ["a.yaml", "b.yaml"])

        occurrences = asyncio.run(
            run_yaml_batch_with_case_ids(
                {"files": files},
                ["case-a", "case-b"],
                {"player_factory": _factory},
            )
        )

        assert [occurrence["caseId"] for occurrence in occurrences] == [
            "case-a",
            "case-b",
        ]
        assert [occurrence["result"]["file"] for occurrence in occurrences] == files
        assert all(occurrence["result"]["success"] for occurrence in occurrences)

    def test_includes_the_setup_occurrence_in_the_case_ids(self, tmp_path):
        files = _scripts(tmp_path, ["main.yaml"])
        setup = _scripts(tmp_path, ["setup.yaml"])[0]

        occurrences = asyncio.run(
            run_yaml_batch_with_case_ids(
                {"files": files, "setup": setup},
                ["setup-case", "main-case"],
                {"player_factory": _factory},
            )
        )

        assert [occurrence["caseId"] for occurrence in occurrences] == [
            "setup-case",
            "main-case",
        ]
        assert occurrences[0]["result"]["file"] == setup
        assert occurrences[1]["result"]["file"] == files[0]

    def test_includes_the_before_all_occurrence_in_the_case_ids(self, tmp_path):
        files = _scripts(tmp_path, ["main.yaml"])
        setup = _scripts(tmp_path, ["setup.yaml"])[0]

        occurrences = asyncio.run(
            run_yaml_batch_with_case_ids(
                {"files": files, "beforeAll": setup},
                ["setup-case", "main-case"],
                {"player_factory": _factory},
            )
        )

        assert [occurrence["caseId"] for occurrence in occurrences] == [
            "setup-case",
            "main-case",
        ]
        assert occurrences[0]["result"]["file"] == setup
        assert occurrences[1]["result"]["file"] == files[0]

    def test_rejects_a_case_id_count_mismatch(self, tmp_path):
        files = _scripts(tmp_path, ["a.yaml", "b.yaml"])

        with pytest.raises(ValueError, match="Batch occurrence identity mismatch"):
            asyncio.run(
                run_yaml_batch_with_case_ids(
                    {"files": files}, ["case-a"], {"player_factory": _factory}
                )
            )

    def test_rejects_duplicate_case_ids(self, tmp_path):
        files = _scripts(tmp_path, ["a.yaml", "b.yaml"])

        with pytest.raises(ValueError, match="case IDs must be unique"):
            asyncio.run(
                run_yaml_batch_with_case_ids(
                    {"files": files},
                    ["case-a", "case-a"],
                    {"player_factory": _factory},
                )
            )

    def test_rejects_reuse_page_without_shared_context(self, tmp_path):
        files = _scripts(tmp_path, ["a.yaml"])

        with pytest.raises(ValueError, match="reusePage requires"):
            asyncio.run(
                run_yaml_batch_with_case_ids(
                    {"files": files, "reusePage": True},
                    ["case-a"],
                    {"player_factory": _factory},
                )
            )


class TestRunYamlBatchInRstest:
    @pytest.mark.skip(reason=_SKIP)
    def test_runs_the_shared_batch_executor_without_duplicate_summary_output_and_writes_result_files(
        self,
    ):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_writes_all_batch_results_before_surfacing_aggregated_failures(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_writes_duplicate_yaml_occurrences_to_distinct_result_files(self):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_writes_occurrence_results_before_rethrowing_an_unexpected_batch_error(
        self,
    ):
        pass

    @pytest.mark.skip(reason=_SKIP)
    def test_throws_when_a_batch_result_has_no_matching_output_target(self):
        pass
