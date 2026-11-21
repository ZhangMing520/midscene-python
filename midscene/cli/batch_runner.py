"""Thin YAML batch runner (upstream packages/cli/src/batch-runner.ts)."""

from typing import Any, Callable, Dict, List

from midscene.cli.execution_summary import (
    get_result_files_by_type,
    is_batch_successful,
)
from midscene.cli.yaml_batch_error import YamlBatchExecutionError
from midscene.cli.yaml_batch_executor import (
    _apply_web_overrides,
    parse_batch_config,
    run_yaml_batch,
)


class BatchRunner:
    """Run a batch of YAML scripts and expose the collected results."""

    def __init__(
        self,
        config: Dict[str, Any],
        player_factory: Callable[[str, str], Any],
    ):
        """player_factory(yaml_content, file_path) -> ScriptPlayer-like object
        with run()/status/failed_tasks/output_path/result."""
        self._raw_config = config
        self._player_factory = player_factory
        self.config = parse_batch_config(config)
        self.results: List[Dict[str, Any]] = []
        self.hook_error = None

    async def run(self) -> List[Dict[str, Any]]:
        self.results = []
        self.hook_error = None
        state: Dict[str, Any] = {}
        try:
            self.results = list(
                await run_yaml_batch(
                    self._raw_config, self._player_factory, state
                )
            )
            return self.results
        except YamlBatchExecutionError as error:
            self.results = list(error.results)
            raise
        finally:
            self.hook_error = state.get("hook_error")

    def get_results(self) -> List[Dict[str, Any]]:
        return list(self.results)

    def get_failed_files(self) -> List[str]:
        return get_result_files_by_type(self.results, "failed")

    def get_successful_files(self) -> List[str]:
        return get_result_files_by_type(self.results, "success")

    def get_not_executed_files(self) -> List[str]:
        return get_result_files_by_type(self.results, "notExecuted")

    def _apply_web_overrides(
        self, content: str, overrides: Dict[str, Any]
    ) -> str:
        """Delegate to the executor's web override helper."""
        return _apply_web_overrides(content, overrides)

    @property
    def passed(self) -> bool:
        return is_batch_successful(self.results, self.hook_error)
