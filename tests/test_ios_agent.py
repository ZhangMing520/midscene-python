"""Port of upstream packages/ios/tests/unit-test/agent.test.ts.

Only the cases covered by the former aggregate ``tests/test_ios.py`` are kept.
The Node-only test-runner nodes, ``agentFromWebDriverAgent`` override loading
and ``launch``/``terminate`` wrappers are not part of the Python API.
"""

from unittest.mock import AsyncMock

import pytest

from midscene.ios.agent import IOSAgent
from midscene.ios.device import IOSDevice


def test_should_create_ios_agent_with_device():
    """should create IOSAgent with device."""

    device = IOSDevice()
    agent = IOSAgent(device)

    assert isinstance(agent, IOSAgent)
    assert agent.interface is device
    assert agent.interface_type.value == "ios"


@pytest.mark.asyncio
async def test_should_execute_wda_request_through_call_action_in_action_space():
    """should execute WDA request through callActionInActionSpace."""

    payload = {"value": {"state": "ready"}}
    device = IOSDevice()
    device._connected = True
    device.run_wda_request = AsyncMock(return_value=payload)
    agent = IOSAgent(device)

    result = await agent._call_action_in_action_space(
        "RunWdaRequest", {"method": "GET", "endpoint": "/status"}
    )

    assert result == payload
    device.run_wda_request.assert_awaited_once_with("GET", "/status", None)
