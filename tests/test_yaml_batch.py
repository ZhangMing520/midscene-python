"""Rstest YAML batch wrapper (upstream framework/yaml-batch.test.ts).

The upstream wrapper (``runYamlBatchInRstest``) and the case-id aware executor
(``runYamlBatchWithCaseIds``) are part of the Node rstest integration. The
Python CLI exposes ``run_yaml_batch`` only, so this suite is Node-only.
"""

import pytest

_SKIP = (
    "Python CLI does not implement the rstest YAML batch wrapper or "
    "runYamlBatchWithCaseIds"
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
