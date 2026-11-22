"""Synced from upstream packages/shared/tests/unit-test/logger.test.ts."""

import asyncio

import pytest

from midscene.shared import logger as logger_module


def test_overrides_the_file_log_directory_for_the_current_process(tmp_path):
    """overrides the file log directory for the current process"""
    try:
        logger_module.set_log_directory_resolver(lambda: str(tmp_path))
        assert logger_module.get_log_directory() == str(tmp_path)
    finally:
        logger_module.set_log_directory_resolver(None)


def test_does_not_throw_when_console_logging_cannot_write(monkeypatch):
    """does not throw when console logging cannot write"""
    debug_calls = []
    warn_calls = []

    monkeypatch.setattr(
        logger_module, "_debug_fn", lambda *args: debug_calls.append(args)
    )

    def failing_warn(*args):
        warn_calls.append(args)
        raise OSError("write EIO")

    monkeypatch.setattr(logger_module, "_console_warn", failing_warn)

    debug_log = logger_module.get_debug("logger:test", {"console": True})
    error = Exception("adb unavailable")

    debug_log("android scan failed:", error)

    assert debug_calls == [("android scan failed:", error)]
    assert warn_calls == [("[Midscene]", "android scan failed:", error)]


@pytest.mark.asyncio
async def test_isolates_concurrent_console_handlers_and_restores_ordinary_sdk_output(
    monkeypatch,
):
    """isolates concurrent console handlers and restores ordinary SDK output"""
    debug_calls = []
    warn_calls = []
    monkeypatch.setattr(
        logger_module, "_debug_fn", lambda *args: debug_calls.append(args)
    )
    monkeypatch.setattr(
        logger_module, "_console_warn", lambda *args: warn_calls.append(args)
    )

    first = []
    second = []
    log = logger_module.get_debug("logger:scoped", {"console": True})

    async def first_run():
        await asyncio.sleep(0)
        log("first warning")
        logger_module.log_report("first report")

    async def second_run():
        await asyncio.sleep(0)
        log("second warning")

    await asyncio.gather(
        logger_module.run_with_console_log_handler(first.append, first_run),
        logger_module.run_with_console_log_handler(second.append, second_run),
    )

    assert [entry["message"] for entry in first] == ["first warning", "first report"]
    assert [entry["message"] for entry in second] == ["second warning"]
    assert warn_calls == []
    assert ("first warning",) in debug_calls

    log("outside warning")
    assert warn_calls == [("[Midscene]", "outside warning")]


@pytest.mark.asyncio
async def test_keeps_nested_asynchronous_warning_scopes_and_per_call_metadata_isolated(
    monkeypatch,
):
    """keeps nested asynchronous warning scopes and per-call metadata isolated"""
    monkeypatch.setattr(logger_module, "_debug_fn", lambda *args: None)
    entries = []

    async def worker(case_name):
        async def inner():
            await asyncio.sleep(0)
            error = Exception(f"{case_name} failure")
            logger_module.get_debug(
                "logger:metadata",
                {
                    "console": True,
                    "warning": {
                        "kind": "model-request-retry",
                        "modelName": "model",
                        "error": error,
                        "callId": case_name,
                        "attempt": 1,
                        "maxAttempts": 2,
                        "delayMs": 2000,
                    },
                },
            )("request failed", error)

        await logger_module.run_with_console_log_scope(
            {
                "projectName": "web",
                "caseName": case_name,
                "phase": "steps",
                "stepIndex": 0,
                "node": "aiAct",
            },
            inner,
        )

    async def outer():
        await asyncio.gather(worker("first"), worker("second"))

    async def root():
        await logger_module.run_with_console_log_scope(
            {"projectName": "web", "sourcePath": "cases/shop.yaml"}, outer
        )

    await logger_module.run_with_console_log_handler(entries.append, root)

    assert [
        {
            "caseName": entry["scope"]["caseName"],
            "sourcePath": entry["scope"]["sourcePath"],
            "callId": entry["warning"]["callId"],
            "error": str(entry["warning"]["error"]),
        }
        for entry in entries
    ] == [
        {
            "caseName": case_name,
            "sourcePath": "cases/shop.yaml",
            "callId": case_name,
            "error": f"{case_name} failure",
        }
        for case_name in ("first", "second")
    ]
    assert "Error: first failure" in entries[0]["message"]
    assert entries[0]["args"][1] is entries[0]["warning"]["error"]
