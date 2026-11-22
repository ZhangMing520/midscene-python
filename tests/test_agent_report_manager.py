"""Synced from upstream packages/core/tests/unit-test/agent-report-manager.test.ts.

The Python port keeps report state on the Agent and implements the upstream
AgentReportManager behavior as module-level helpers in
``midscene.core.agent.agent_report_manager``. These tests drive those helpers
through a minimal fake Agent, so the same listener/serialization/finalization
contract is exercised without constructing a real device.
"""

from types import SimpleNamespace

import pytest

from midscene.core.agent import agent_report_manager as report_manager
from midscene.core.agent import report_file_name


class FakeAgent:
    """Minimal Agent surface used by the report helpers."""

    def __init__(self, group_name="first group"):
        self.options = SimpleNamespace(
            group_name=group_name, group_description=""
        )
        self.interface_type = "puppeteer"
        self.destroyed = False
        self._report_builder = None
        self._dump_update_listeners = []
        self._report_finalized = None
        self._report_file_name = None
        self._report_artifact_store = None
        self._last_execution = None
        self._execution_index_by_runner = {}
        self.serialize_calls = 0

    def _check_not_destroyed(self):
        if self.destroyed:
            raise RuntimeError("Agent has been destroyed")

    def _get_report_builder(self):
        return report_manager.get_report_builder(self)

    def _report_name(self):
        return report_file_name.report_name(self)

    def dump_data_string(self, opt=None):
        self.serialize_calls += 1
        return report_manager.dump_data_string(self, opt)

    async def flush_report(self):
        return None

    async def reset_dump(self):
        return await report_manager.reset_dump(self)

    async def finalize_report(self):
        return await report_manager.finalize_report(self)

    def append_execution_dump(self, execution, runner=None):
        return report_manager.append_execution_dump(self, execution, runner)

    def add_dump_update_listener(self, listener):
        return report_manager.add_dump_update_listener(self, listener)

    def remove_dump_update_listener(self, listener):
        return report_manager.remove_dump_update_listener(self, listener)

    def clear_dump_update_listeners(self):
        return report_manager.clear_dump_update_listeners(self)

    def notify_dump_update_listeners(self, execution=None):
        return report_manager.notify_dump_update_listeners(self, execution)


def _execution(execution_id):
    return {"id": execution_id, "name": execution_id, "logTime": 0, "tasks": []}


def create_manager():
    agent = FakeAgent()
    return agent


def test_does_not_serialize_a_dump_when_no_listeners_are_registered():
    """does not serialize a dump when no listeners are registered"""
    agent = create_manager()
    agent.append_execution_dump(_execution("first"))
    assert agent.serialize_calls == 0

    agent.notify_dump_update_listeners()
    assert agent.serialize_calls == 0

    remove = agent.add_dump_update_listener(lambda *_: None)
    remove()
    agent.notify_dump_update_listeners()
    assert agent.serialize_calls == 0

    agent.add_dump_update_listener(lambda *_: None)
    agent.clear_dump_update_listeners()
    agent.notify_dump_update_listeners()
    assert agent.serialize_calls == 0


def test_serializes_once_and_shares_the_same_update_with_all_registered_listeners():
    """serializes once and shares the same update with all registered listeners"""
    agent = create_manager()
    current = _execution("first")
    agent.append_execution_dump(current)
    first = []
    second = []
    agent.add_dump_update_listener(lambda dump, execution: first.append((dump, execution)))
    agent.add_dump_update_listener(lambda dump, execution: second.append((dump, execution)))

    agent.notify_dump_update_listeners(current)

    assert agent.serialize_calls == 1
    assert len(first) == 1
    assert len(second) == 1
    dump_string = first[0][0]
    assert first[0] == (dump_string, current)
    assert second[0] == (dump_string, current)


@pytest.mark.asyncio
async def test_retains_listeners_across_report_boundaries_and_captures_independent_exports():
    """retains listeners across report boundaries and captures independent exports"""
    agent = create_manager()
    calls = []
    remove = agent.add_dump_update_listener(
        lambda dump, execution: calls.append((dump, execution))
    )
    agent.append_execution_dump(_execution("first"))
    agent.notify_dump_update_listeners()
    first = calls[0][0]
    first_name = agent._report_name()

    agent.options.group_name = "second group"
    await agent.reset_dump()
    assert agent._report_name() != first_name

    agent.append_execution_dump(_execution("second"))
    agent.notify_dump_update_listeners()

    import json

    assert [item["id"] for item in json.loads(first)["executions"]] == ["first"]
    second_dump = json.loads(calls[1][0])
    assert second_dump["groupName"] == "second group"
    assert [item["id"] for item in second_dump["executions"]] == ["second"]

    remove()
    agent.notify_dump_update_listeners()
    assert len(calls) == 2

    await agent.finalize_report()
    assert agent._get_report_builder().to_dict()["executions"] == []


@pytest.mark.skip(
    reason="Python report helpers have no external-busy gating "
    "(isExternallyBusy / withReportOperation) to reject live resets"
)
@pytest.mark.asyncio
async def test_rejects_external_ownership_and_live_operations_without_owning_execution_resources():
    """rejects external ownership and live operations without owning execution resources"""
    pass


@pytest.mark.skip(
    reason="Python report helpers do not implement bindRunner/assertRunnerCurrent "
    "runner ownership tracking"
)
@pytest.mark.asyncio
async def test_retains_runner_ownership_across_finalization_and_resets():
    """retains runner ownership across finalization and resets"""
    pass
