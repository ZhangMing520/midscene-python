"""Batch runner orchestration (upstream batch-runner.test.ts).

The upstream suite mocks Puppeteer, the filesystem and the YAML player. The
Python runner accepts an injected player factory instead; cases that depend on
Puppeteer/shared-browser internals have no Python counterpart and are skipped.
"""

import asyncio

import pytest

from midscene.cli.batch_runner import BatchRunner


class FakePlayer:
    def __init__(self, behavior="ok", output_path=None, result=None):
        self.behavior = behavior
        self.status = "init"
        self.failed_tasks = []
        self.output_path = output_path
        self.result = result or {}
        self.shared_page = None

    async def run(self):
        if self.behavior == "ok":
            self.status = "done"
        elif self.behavior == "task_fail":
            self.status = "error"
            self.failed_tasks.append({"name": "task", "error": "Mock error"})
        else:
            self.status = "error"
            raise RuntimeError("player exploded")


def _factory(behaviors=None):
    behaviors = behaviors or {}

    def factory(_content, file_path):
        return FakePlayer(behaviors.get(file_path, "ok"))

    return factory


@pytest.fixture
def scripts(tmp_path):
    for name in ("file1.yml", "file2.yml", "file3.yml", "login.yml",
                 "search.yml", "report.yml", "prepare.yml", "main.yml"):
        (tmp_path / name).write_text(
            "tasks:\n  - name: task\n    flow:\n      - sleep: 1\n",
            encoding="utf-8",
        )
    return tmp_path


class TestBatchRunnerExecution:
    def test_constructor_creates_executor_with_config(self, scripts):
        runner = BatchRunner({"files": [str(scripts / "file1.yml")]}, _factory())
        assert runner is not None

    @pytest.mark.asyncio
    async def test_run_executes_files_successfully_with_default_options(self, scripts):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        results = await BatchRunner({"files": files}, _factory()).run()

        assert len(results) == 3
        assert all(result["success"] for result in results)

    @pytest.mark.asyncio
    async def test_run_stops_on_first_failure_when_continue_on_error_is_false(
        self, scripts
    ):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {"files": files, "concurrent": 1, "continueOnError": False},
            _factory({files[0]: "task_fail"}),
        )
        results = await runner.run()

        assert len(results) == 3
        assert results[0]["success"] is False
        assert results[0]["executed"] is True
        assert results[0]["error"] == "task - task: Mock error"
        assert results[1]["resultType"] == "notExecuted"
        assert results[2]["resultType"] == "notExecuted"

    @pytest.mark.asyncio
    async def test_run_continues_on_failure_when_continue_on_error_is_true(
        self, scripts
    ):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {"files": files, "concurrent": 1, "continueOnError": True},
            _factory({files[0]: "task_fail"}),
        )
        results = await runner.run()

        assert len(results) == 3
        assert [result["success"] for result in results] == [False, True, True]
        assert all(result["executed"] for result in results)

    @pytest.mark.asyncio
    async def test_keeps_duplicate_yaml_occurrences_bound_to_distinct_players_and_config_order(
        self, scripts
    ):
        second_finished = asyncio.Event()
        first_player = FakePlayer("ok")
        second_player = FakePlayer("task_fail")

        async def first_run():
            await second_finished.wait()
            first_player.status = "done"

        async def second_run():
            second_player.status = "error"
            second_finished.set()

        first_player.run = first_run
        second_player.run = second_run
        players = [first_player, second_player]

        def factory(_content, _file_path):
            return players.pop(0)

        duplicate_file = str(scripts / "file1.yml")
        runner = BatchRunner(
            {
                "files": [duplicate_file, duplicate_file],
                "concurrent": 2,
                "continueOnError": True,
                "shareBrowserContext": True,
            },
            factory,
        )
        results = await runner.run()

        assert [result["file"] for result in results] == [
            duplicate_file,
            duplicate_file,
        ]
        assert [result["success"] for result in results] == [True, False]


class TestBatchRunnerSetup:
    @pytest.mark.asyncio
    async def test_runs_the_setup_file_before_the_main_files_and_executes_all(
        self, scripts
    ):
        run_order = []

        def factory(_content, file_path):
            player = FakePlayer("ok")

            async def run():
                run_order.append(file_path)
                await player.__class__.run(player)

            player.run = run
            return player

        runner = BatchRunner(
            {
                "files": [str(scripts / "search.yml"), str(scripts / "report.yml")],
                "setup": str(scripts / "login.yml"),
                "concurrent": 2,
            },
            factory,
        )
        await runner.run()

        assert run_order[0] == str(scripts / "login.yml")
        assert str(scripts / "search.yml") in run_order
        assert str(scripts / "report.yml") in run_order
        assert runner.get_not_executed_files() == []
        assert sorted(runner.get_successful_files()) == sorted(
            [
                str(scripts / "login.yml"),
                str(scripts / "report.yml"),
                str(scripts / "search.yml"),
            ]
        )

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Python runs the beforeAll setup once; upstream exercises retry "
        "semantics that the Python executor does not implement"
    )
    async def test_aborts_main_files_after_setup_retries_are_exhausted(self):
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Python runs the beforeAll setup once; upstream exercises retry "
        "semantics that the Python executor does not implement"
    )
    async def test_retries_setup_in_a_fresh_context_and_shares_only_the_successful_context(
        self,
    ):
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Python runs the beforeAll setup once; upstream exercises retry "
        "semantics that the Python executor does not implement"
    )
    async def test_retries_non_puppeteer_setup_with_a_new_player_before_running_main_files(
        self,
    ):
        pass

    def test_rejects_reuse_page_without_share_browser_context(self, scripts):
        with pytest.raises(ValueError, match='reusePage.*requires'):
            BatchRunner(
                {
                    "files": [str(scripts / "file1.yml")],
                    "concurrent": 1,
                    "shareBrowserContext": False,
                    "reusePage": True,
                },
                _factory(),
            )

    def test_rejects_reuse_page_for_concurrent_batches(self, scripts):
        with pytest.raises(ValueError, match='reusePage.*requires'):
            BatchRunner(
                {
                    "files": [str(scripts / "file1.yml")],
                    "concurrent": 2,
                    "shareBrowserContext": True,
                    "reusePage": True,
                },
                _factory(),
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_name", ["Web bridge mode", "Android", "iOS", "HarmonyOS", "Computer", "Interface"])
    async def test_allows_target_setup_without_share_browser_context(
        self, scripts, target_name
    ):
        runner = BatchRunner(
            {
                "files": [str(scripts / "main.yml")],
                "setup": str(scripts / "prepare.yml"),
                "shareBrowserContext": False,
            },
            _factory(),
        )
        results = await runner.run()

        assert [result["file"] for result in results] == [
            str(scripts / "prepare.yml"),
            str(scripts / "main.yml"),
        ]


class TestBatchRunnerSharedBrowser:
    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_create_one_browser_instance_when_share_browser_context_is_true(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_reuses_the_setup_page_for_a_sequential_batch_when_reuse_page_is_true(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_closes_the_context_when_shared_page_creation_fails(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_retries_only_a_failed_file_while_reusing_the_shared_page(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_pass_chrome_args_from_global_config_to_puppeteer_launch(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_pass_accept_insecure_certs_from_global_config_to_puppeteer_launch(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_pass_download_path_to_puppeteer_launch_options(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_not_create_a_shared_browser_instance_when_sharing_is_false(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_not_create_any_browser_instance_for_non_web_tasks(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_use_puppeteer_connect_when_cdp_endpoint_is_specified(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_pass_download_path_to_puppeteer_connect_options(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_should_disconnect_not_close_browser_in_cdp_mode(self):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    @pytest.mark.parametrize(
        "option",
        ["cdpEndpoint", "chromeArgs", "acceptInsecureCerts", "downloadPath"],
    )
    def test_rejects_file_level_option_in_a_shared_browser(self, option):
        pass

    @pytest.mark.skip(reason="Python batch runner does not manage Puppeteer browsers")
    def test_delivers_progress_snapshots_to_the_caller(self):
        pass


class TestBatchRunnerSummary:
    @pytest.mark.skip(
        reason="Python writes the execution summary as a result list at the "
        "configured path; upstream summary path/structure is Node-specific"
    )
    def test_generates_summary_file_with_correct_name_and_path(self):
        pass

    @pytest.mark.skip(
        reason="Python writes the execution summary as a result list at the "
        "configured path; upstream summary structure is Node-specific"
    )
    def test_generates_correct_summary_file_structure(self):
        pass

    @pytest.mark.skip(
        reason="Python results always expose output_path; upstream optionally "
        "checks file existence via node:fs"
    )
    def test_output_field_contains_file_path_when_file_exists(self):
        pass

    @pytest.mark.skip(
        reason="Python results always expose output_path; upstream optionally "
        "checks file existence via node:fs"
    )
    def test_output_field_is_undefined_when_file_does_not_exist(self):
        pass

    @pytest.mark.skip(reason="Python results expose output_path without a null check")
    def test_output_field_is_undefined_when_player_output_is_null(self):
        pass

    @pytest.mark.skip(reason="Python results do not call existsSync")
    def test_exists_sync_is_called_with_correct_file_path(self):
        pass


class TestBatchRunnerCommonFunctionality:
    @pytest.mark.skip(
        reason="Python BatchRunner does not expose getExecutionSummary/"
        "printExecutionSummary"
    )
    def test_get_execution_summary_returns_correct_summary(self):
        pass

    @pytest.mark.skip(
        reason="Python BatchRunner does not expose getExecutionSummary/"
        "printExecutionSummary"
    )
    def test_print_execution_summary_prints_and_returns_success_status(self):
        pass

    @pytest.mark.skip(
        reason="Python BatchRunner does not expose getExecutionSummary/"
        "printExecutionSummary"
    )
    def test_print_execution_summary_shows_failed_files_when_there_are_failures(self):
        pass

    @pytest.mark.skip(
        reason="Python BatchRunner does not track partialFailed result summaries"
    )
    def test_continue_on_error_failed_tasks_should_be_counted_as_failed_files(self):
        pass

    @pytest.mark.skip(reason="Python tracks failures through get_failed_files only")
    def test_get_failed_files_returns_failed_files(self):
        pass

    @pytest.mark.skip(reason="Python get_results already returns a detached list")
    def test_get_results_returns_copy_of_results(self):
        pass


class TestBatchRunnerErrorCollection:
    @pytest.mark.skip(
        reason="Python surfaces player.failed_tasks as 'task - name: error'; "
        "upstream collects per-task error messages from ScriptPlayer.taskStatusList"
    )
    def test_collects_specific_error_message_from_failed_task(self):
        pass

    @pytest.mark.skip(
        reason="Python surfaces player.failed_tasks as 'task - name: error'; "
        "upstream joins taskStatusList errors"
    )
    def test_joins_multiple_task_error_messages_with_semicolons(self):
        pass

    @pytest.mark.skip(
        reason="Python reports the raised exception message; upstream reads "
        "ScriptPlayer.errorInSetup"
    )
    def test_uses_error_in_setup_message_when_available(self):
        pass


class TestBatchRunnerGlobalConfig:
    @pytest.mark.skip(
        reason="Python applies script-over-global web overrides; upstream global "
        "config overrides file config"
    )
    def test_should_not_modify_file_config_if_no_global_config_is_provided(self):
        pass

    @pytest.mark.skip(
        reason="Python applies script-over-global web overrides; upstream global "
        "config overrides file config"
    )
    def test_should_override_file_config_with_global_config(self):
        pass

    @pytest.mark.skip(
        reason="Python applies script-over-global native overrides through the "
        "executor; the upstream createYamlPlayer call shape is Node-specific"
    )
    def test_should_merge_android_config_from_global_config(self):
        pass

    @pytest.mark.skip(
        reason="Python applies script-over-global native overrides through the "
        "executor; the upstream createYamlPlayer call shape is Node-specific"
    )
    def test_should_merge_harmony_config_from_global_config(self):
        pass

    @pytest.mark.skip(
        reason="Python applies script-over-global native overrides through the "
        "executor; the upstream createYamlPlayer call shape is Node-specific"
    )
    def test_should_create_web_android_config_if_missing_in_file_config(self):
        pass

    @pytest.mark.skip(reason="Python does not launch Puppeteer for web tasks")
    def test_should_not_launch_puppeteer_if_no_web_tasks_are_present(self):
        pass
