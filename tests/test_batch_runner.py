"""Batch runner orchestration (upstream batch-runner.test.ts).

The upstream suite mocks Puppeteer, the filesystem and the YAML player. The
Python runner accepts an injected player factory instead; cases that depend on
Puppeteer/shared-browser internals have no Python counterpart and are skipped.
"""

import asyncio
from pathlib import Path

import pytest
import yaml

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
    async def test_aborts_main_files_after_setup_retries_are_exhausted(self, scripts):
        run_order = []
        login = str(scripts / "login.yml")
        search = str(scripts / "search.yml")
        report = str(scripts / "report.yml")

        def factory(_content, file_path):
            player = FakePlayer("task_fail" if file_path == login else "ok")
            original_run = player.run

            async def run():
                run_order.append(Path(file_path).name)
                await original_run()

            player.run = run
            return player

        runner = BatchRunner(
            {
                "files": [search, report],
                "setup": login,
                "concurrent": 2,
                "retry": 1,
                "shareBrowserContext": True,
            },
            factory,
        )
        results = await runner.run()

        # The main files must never run once the prerequisite setup fails.
        assert run_order == ["login.yml", "login.yml"]
        assert runner.get_failed_files() == [login]
        assert sorted(runner.get_not_executed_files()) == sorted([report, search])
        setup_result = next(result for result in results if result["file"] == login)
        assert setup_result["success"] is False
        assert setup_result["attempts"] == [
            {"attempt": 1, "success": False},
            {"attempt": 2, "success": False},
        ]

    @pytest.mark.asyncio
    async def test_retries_setup_in_a_fresh_context_and_shares_only_the_successful_context(
        self,
        scripts,
    ):  # noqa: E501
        run_order = []
        setup_players = []
        main_players = []
        setup_creation_count = 0
        shared_page_holder = {}

        def factory(_content, file_path):
            nonlocal setup_creation_count
            name = Path(file_path).name
            if name == "login.yml":
                setup_creation_count += 1
            should_succeed = name != "login.yml" or setup_creation_count > 1
            player = FakePlayer("ok" if should_succeed else "task_fail")
            page = object()
            player.shared_page = page
            original_run = player.run

            async def run():
                run_order.append(name)
                await original_run()

            player.run = run
            if name == "login.yml":
                setup_players.append(page)
                if should_succeed:
                    shared_page_holder["page"] = page
            else:
                main_players.append(shared_page_holder.get("page"))
            return player

        login = str(scripts / "login.yml")
        search = str(scripts / "search.yml")
        report = str(scripts / "report.yml")
        runner = BatchRunner(
            {
                "files": [search, report],
                "setup": login,
                "concurrent": 1,
                "retry": 1,
                "shareBrowserContext": True,
                "reusePage": True,
            },
            factory,
        )
        results = await runner.run()

        assert run_order[:2] == ["login.yml", "login.yml"]
        assert sorted(run_order[2:]) == ["report.yml", "search.yml"]
        assert setup_creation_count == 2
        assert len(setup_players) == 2
        assert setup_players[0] is not setup_players[1]
        assert main_players == [setup_players[1], setup_players[1]]
        setup_result = next(result for result in results if result["file"] == login)
        assert setup_result["success"] is True
        assert setup_result["attempts"] == [
            {"attempt": 1, "success": False},
            {"attempt": 2, "success": True},
        ]
        assert runner.get_not_executed_files() == []

    @pytest.mark.asyncio
    async def test_retries_non_puppeteer_setup_with_a_new_player_before_running_main_files(
        self,
        scripts,
    ):
        run_order = []
        setup_creation_count = 0
        prepare = str(scripts / "prepare.yml")
        main = str(scripts / "main.yml")

        def factory(_content, file_path):
            nonlocal setup_creation_count
            name = Path(file_path).name
            if name == "prepare.yml":
                setup_creation_count += 1
            should_succeed = name != "prepare.yml" or setup_creation_count > 1
            player = FakePlayer("ok" if should_succeed else "task_fail")
            original_run = player.run

            async def run():
                run_order.append(name)
                await original_run()

            player.run = run
            return player

        runner = BatchRunner(
            {
                "files": [main],
                "setup": prepare,
                "shareBrowserContext": False,
                "retry": 1,
            },
            factory,
        )
        results = await runner.run()

        assert run_order == ["prepare.yml", "prepare.yml", "main.yml"]
        assert setup_creation_count == 2
        setup_result = next(
            result for result in results if result["file"] == prepare
        )
        assert setup_result["success"] is True
        assert setup_result["attempts"] == [
            {"attempt": 1, "success": False},
            {"attempt": 2, "success": True},
        ]

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

    @pytest.mark.asyncio
    async def test_exists_sync_is_called_with_correct_file_path(self, scripts):
        output_file = scripts / "output.json"
        output_file.write_text("{}", encoding="utf-8")

        def factory(_content, _file_path):
            return FakePlayer("ok", output_path=str(output_file))

        results = await BatchRunner(
            {"files": [str(scripts / "file1.yml")]}, factory
        ).run()

        assert results[0]["output"] == str(output_file)


class TestBatchRunnerCommonFunctionality:
    @pytest.mark.asyncio
    async def test_get_execution_summary_returns_correct_summary(self, scripts):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {"files": files, "summary": "test-summary.json"}, _factory()
        )
        await runner.run()

        summary = runner.get_execution_summary()

        assert summary["total"] == 3
        assert summary["successful"] == 3
        assert summary["failed"] == 0
        assert summary["notExecuted"] == 0
        assert isinstance(summary["totalDuration"], (int, float))

    @pytest.mark.asyncio
    async def test_print_execution_summary_prints_and_returns_success_status(
        self, scripts, capsys
    ):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {"files": files, "summary": "test-summary.json"}, _factory()
        )
        await runner.run()

        success = runner.print_execution_summary()
        output = capsys.readouterr().out

        assert success is True
        assert "📊 Execution Summary:" in output
        assert "🎉 All files executed successfully!" in output

    @pytest.mark.asyncio
    async def test_print_execution_summary_shows_failed_files_when_there_are_failures(
        self, scripts, capsys
    ):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {
                "files": files,
                "continueOnError": True,
                "summary": "test-summary.json",
            },
            _factory({files[0]: "task_fail"}),
        )
        await runner.run()

        success = runner.print_execution_summary()
        output = capsys.readouterr().out

        assert success is False
        assert "❌ Failed files" in output

    @pytest.mark.asyncio
    async def test_continue_on_error_failed_tasks_should_be_counted_as_failed_files(
        self, scripts, capsys
    ):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]

        def factory(_content, file_path):
            player = FakePlayer("ok")
            if file_path == files[0]:
                player.failed_tasks.append(
                    {
                        "name": "assertion",
                        "error": "Assertion failed: this is not a search engine",
                    }
                )
            return player

        runner = BatchRunner(
            {
                "files": files,
                "continueOnError": True,
                "summary": "test-summary.json",
            },
            factory,
        )
        await runner.run()

        summary = runner.get_execution_summary()
        success = runner.print_execution_summary()
        output = capsys.readouterr().out

        assert summary["partialFailed"] == 1
        assert summary["failed"] == 0
        assert summary["successful"] == 2
        assert success is False
        assert "⚠️  Partial failed files" in output

    @pytest.mark.asyncio
    async def test_get_failed_files_returns_failed_files(self, scripts):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner(
            {"files": files, "continueOnError": True},
            _factory({files[0]: "task_fail"}),
        )
        await runner.run()

        assert runner.get_failed_files() == [files[0]]

    @pytest.mark.asyncio
    async def test_get_results_returns_copy_of_results(self, scripts):
        files = [
            str(scripts / "file1.yml"),
            str(scripts / "file2.yml"),
            str(scripts / "file3.yml"),
        ]
        runner = BatchRunner({"files": files}, _factory())
        await runner.run()

        results = runner.get_results()

        assert len(results) == 3
        results.append({})
        assert len(runner.get_results()) == 3


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
    @pytest.mark.asyncio
    async def test_should_not_modify_file_config_if_no_global_config_is_provided(
        self, scripts
    ):
        path = scripts / "file1.yml"
        original = (
            "tasks:\n"
            "  - name: test task\n"
            "    flow:\n"
            "      - ai: do something\n"
            "web:\n"
            "  url: http://file.com\n"
            "  userAgent: file-agent\n"
        )
        path.write_text(original, encoding="utf-8")
        captured = []

        def factory(content, file_path):
            captured.append(content)
            return FakePlayer("ok")

        await BatchRunner({"files": [str(path)]}, factory).run()

        assert captured == [original]

    @pytest.mark.asyncio
    async def test_should_override_file_config_with_global_config(self, scripts):
        path = scripts / "file1.yml"
        path.write_text(
            "tasks:\n"
            "  - name: test task\n"
            "    flow:\n"
            "      - ai: do something\n"
            "web:\n"
            "  url: http://file.com\n"
            "  userAgent: file-agent\n",
            encoding="utf-8",
        )
        captured = []

        def factory(content, file_path):
            captured.append(content)
            return FakePlayer("ok")

        await BatchRunner(
            {
                "files": [str(path)],
                "web": {
                    "url": "http://global.com",
                    "serve": "/global/serve",
                    "userAgent": "global-agent",
                },
            },
            factory,
        ).run()

        script = yaml.safe_load(captured[0])
        assert script["web"]["url"] == "http://global.com"
        assert script["web"]["userAgent"] == "global-agent"
        assert script["web"]["serve"] == "/global/serve"

    @pytest.mark.asyncio
    async def test_should_merge_android_config_from_global_config(self, scripts):
        path = scripts / "file1.yml"
        path.write_text(
            "tasks:\n"
            "  - name: test task\n"
            "    flow:\n"
            "      - ai: do something\n"
            "android:\n"
            "  deviceId: file-device\n"
            "  launch: file.app\n",
            encoding="utf-8",
        )
        captured = []

        def factory(content, file_path):
            captured.append(content)
            return FakePlayer("ok")

        await BatchRunner(
            {
                "files": [str(path)],
                "android": {"launch": "global.app", "deviceId": "global-device"},
            },
            factory,
        ).run()

        script = yaml.safe_load(captured[0])
        assert script["android"] == {
            "launch": "global.app",
            "deviceId": "global-device",
        }

    @pytest.mark.asyncio
    async def test_should_merge_harmony_config_from_global_config(self, scripts):
        path = scripts / "file1.yml"
        path.write_text(
            "tasks:\n"
            "  - name: test task\n"
            "    flow:\n"
            "      - ai: do something\n"
            "harmony:\n"
            "  launch: file.bundle/FileAbility\n"
            "  deviceId: file-harmony-device\n"
            "  autoDismissKeyboard: false\n"
            "  hdcPath: /file/path/to/hdc\n",
            encoding="utf-8",
        )
        captured = []

        def factory(content, file_path):
            captured.append(content)
            return FakePlayer("ok")

        await BatchRunner(
            {
                "files": [str(path)],
                "harmony": {
                    "launch": "global.bundle/GlobalAbility",
                    "deviceId": "global-harmony-device",
                    "autoDismissKeyboard": True,
                },
            },
            factory,
        ).run()

        script = yaml.safe_load(captured[0])
        assert script["harmony"] == {
            "launch": "global.bundle/GlobalAbility",
            "deviceId": "global-harmony-device",
            "autoDismissKeyboard": True,
            "hdcPath": "/file/path/to/hdc",
        }

    @pytest.mark.asyncio
    async def test_should_create_web_android_config_if_missing_in_file_config(
        self, scripts
    ):
        path = scripts / "file1.yml"
        path.write_text(
            "tasks:\n"
            "  - name: test task\n"
            "    flow:\n"
            "      - ai: do something\n",
            encoding="utf-8",
        )
        captured = []

        def factory(content, file_path):
            captured.append(content)
            return FakePlayer("ok")

        await BatchRunner(
            {
                "files": [str(path)],
                "web": {"url": "http://global.com"},
                "android": {"deviceId": "global-device"},
            },
            factory,
        ).run()

        script = yaml.safe_load(captured[0])
        assert script["web"]["url"] == "http://global.com"
        assert script["android"]["deviceId"] == "global-device"

    @pytest.mark.skip(reason="Python does not launch Puppeteer for web tasks")
    def test_should_not_launch_puppeteer_if_no_web_tasks_are_present(self):
        pass
