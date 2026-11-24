"""Port of upstream packages/harmony/tests/unit-test/agent.test.ts."""

from unittest.mock import AsyncMock

import pytest

from midscene.harmony.agent import HarmonyAgent, agent_from_hdc_device
from midscene.harmony.device import HarmonyDevice

MODEL_CONFIG = {
    "MIDSCENE_MODEL_NAME": "mock",
    "MIDSCENE_MODEL_API_KEY": "mock",
    "MIDSCENE_MODEL_BASE_URL": "mock",
    "MIDSCENE_MODEL_FAMILY": "doubao-vision",
}


def test_declares_common_and_harmony_test_runner_nodes():
    """declares common and Harmony Test Runner Nodes"""
    names = [node.name for node in HarmonyAgent.get_test_runner_node_definitions()]
    assert len(names) > 0
    assert len(set(names)) == len(names)


def test_should_create_harmony_agent_successfully():
    """should create HarmonyAgent successfully."""

    device = HarmonyDevice()
    agent = HarmonyAgent(device)

    assert agent is not None
    assert agent.interface is device
    assert agent.interface_type.value == "harmony"


@pytest.mark.asyncio
async def test_should_call_page_launch_with_the_given_uri():
    """should call page.launch with the given uri"""

    device = HarmonyDevice("test-device")
    device.launch_app = AsyncMock()
    agent = HarmonyAgent(device, {"modelConfig": MODEL_CONFIG})

    await agent.launch("https://example.com")

    device.launch_app.assert_awaited_once_with("https://example.com")


@pytest.mark.asyncio
async def test_should_call_page_terminate_with_the_given_uri():
    """should call page.terminate with the given uri"""

    device = HarmonyDevice("test-device")
    device.stop_app = AsyncMock()
    agent = HarmonyAgent(device, {"modelConfig": MODEL_CONFIG})

    await agent.terminate("com.huawei.hmos.settings")

    device.stop_app.assert_awaited_once_with("com.huawei.hmos.settings")


@pytest.mark.asyncio
async def test_should_execute_hdc_shell_through_the_action_space():
    """should execute runHdcShell through the action space"""

    device = HarmonyDevice("test-device")
    device.run_hdc_shell = AsyncMock(return_value="hdc-result")
    agent = HarmonyAgent(device, {"modelConfig": MODEL_CONFIG})

    result = await agent.run_hdc_shell("bm dump -n com.example")

    assert result == "hdc-result"
    device.run_hdc_shell.assert_awaited_once_with("bm dump -n com.example")


class FakeDevice:
    interface_type = "harmony"
    instances = []

    def __init__(self, device_id="", options=None):
        self.device_id = device_id
        self.options = options
        self.connect = AsyncMock()
        self.mappings = []
        FakeDevice.instances.append(self)

    def set_app_name_mapping(self, mapping):
        self.mappings.append(mapping)


@pytest.fixture(autouse=True)
def _reset_instances():
    FakeDevice.instances = []


@pytest.mark.asyncio
async def test_should_use_the_first_device_if_no_device_id_is_provided(monkeypatch):
    """should use the first device if no deviceId is provided"""
    mock_devices = [{"deviceId": "device-1"}, {"deviceId": "device-2"}]
    get_devices = AsyncMock(return_value=mock_devices)
    monkeypatch.setattr("midscene.harmony.agent.get_connected_devices", get_devices)
    monkeypatch.setattr("midscene.harmony.agent.HarmonyDevice", FakeDevice)

    agent = await agent_from_hdc_device()

    get_devices.assert_awaited_once()
    assert FakeDevice.instances[0].device_id == "device-1"
    FakeDevice.instances[0].connect.assert_awaited_once()
    assert isinstance(agent, HarmonyAgent)


@pytest.mark.asyncio
async def test_should_use_the_specified_device_id(monkeypatch):
    """should use the specified deviceId"""
    monkeypatch.setattr("midscene.harmony.agent.HarmonyDevice", FakeDevice)

    agent = await agent_from_hdc_device("test-device-id")

    assert FakeDevice.instances[0].device_id == "test-device-id"
    FakeDevice.instances[0].connect.assert_awaited_once()
    assert isinstance(agent, HarmonyAgent)


@pytest.mark.asyncio
async def test_should_pass_options_to_harmony_device(monkeypatch):
    """should pass options to HarmonyDevice"""
    monkeypatch.setattr("midscene.harmony.agent.HarmonyDevice", FakeDevice)

    options = {
        "autoDismissKeyboard": False,
        "hdcPath": "/path/to/hdc",
    }

    await agent_from_hdc_device("test-device-id", options)

    assert FakeDevice.instances[0].device_id == "test-device-id"
    assert FakeDevice.instances[0].options == options


@pytest.mark.asyncio
async def test_should_throw_when_no_harmony_devices_are_connected(monkeypatch):
    """throws a clear error when no HarmonyOS device is connected"""
    monkeypatch.setattr(
        "midscene.harmony.agent.get_connected_devices",
        AsyncMock(return_value=[]),
    )

    with pytest.raises(RuntimeError, match="No HarmonyOS devices found"):
        await agent_from_hdc_device()
