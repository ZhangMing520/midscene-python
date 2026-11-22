"""Port of upstream packages/ios/tests/unit-test/agent.test.ts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from midscene.ios.agent import IOSAgent, agent_from_web_driver_agent
from midscene.ios.device import IOSDevice

MODEL_CONFIG = {
    "MIDSCENE_MODEL_NAME": "mock",
    "MIDSCENE_MODEL_API_KEY": "mock",
    "MIDSCENE_MODEL_BASE_URL": "mock",
    "MIDSCENE_MODEL_FAMILY": "doubao-vision",
}


def test_declares_common_and_ios_test_runner_nodes():
    """declares common and iOS Test Runner Nodes"""
    names = [node.name for node in IOSAgent.get_test_runner_node_definitions()]
    assert len(names) > 0
    assert len(set(names)) == len(names)


def test_should_create_ios_agent_with_device():
    """should create IOSAgent with device."""

    device = IOSDevice()
    agent = IOSAgent(device)

    assert isinstance(agent, IOSAgent)
    assert agent.interface is device
    assert agent.interface_type.value == "ios"


@pytest.mark.asyncio
async def test_should_launch_app_using_call_action_in_action_space():
    """should launch app using callActionInActionSpace."""

    device = IOSDevice()
    device.launch_app = AsyncMock()
    agent = IOSAgent(device, {"modelConfig": MODEL_CONFIG})

    await agent.launch("com.apple.mobilesafari")

    device.launch_app.assert_awaited_once_with("com.apple.mobilesafari")


@pytest.mark.asyncio
async def test_should_terminate_app_by_bundle_id_using_call_action_in_action_space():
    """should terminate app by bundle ID using callActionInActionSpace."""

    device = IOSDevice()
    device.stop_app = AsyncMock()
    agent = IOSAgent(device, {"modelConfig": MODEL_CONFIG})

    await agent.terminate("com.apple.Preferences")

    device.stop_app.assert_awaited_once_with("com.apple.Preferences")


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


class FakeDevice:
    interface_type = "ios"
    instances = []

    def __init__(self, options=None):
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
async def test_should_create_default_ios_device_when_no_override_is_provided(monkeypatch):
    """should create default IOSDevice when no override is provided"""
    monkeypatch.delenv("MIDSCENE_IOS_DEVICE_CLASS_OVERRIDE", raising=False)
    monkeypatch.setattr("midscene.ios.agent.IOSDevice", FakeDevice)

    await agent_from_web_driver_agent({"modelConfig": MODEL_CONFIG})

    assert len(FakeDevice.instances) == 1
    FakeDevice.instances[0].connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_load_override_device_class_from_documented_option(monkeypatch):
    """should load override device class from documented option"""
    monkeypatch.delenv("MIDSCENE_IOS_DEVICE_CLASS_OVERRIDE", raising=False)
    monkeypatch.setattr("midscene.ios.agent.IOSDevice", FakeDevice)
    monkeypatch.setattr(
        "midscene.ios.agent.importlib.import_module",
        lambda name: SimpleNamespace(IOSDevice=FakeDevice),
    )

    await agent_from_web_driver_agent(
        {
            "modelConfig": MODEL_CONFIG,
            "iOSDeviceClassOverride": "test-ios-device-override",
        }
    )

    assert len(FakeDevice.instances) == 1
    FakeDevice.instances[0].connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_load_override_device_class_from_env(monkeypatch):
    """should load override device class from env"""
    monkeypatch.setenv(
        "MIDSCENE_IOS_DEVICE_CLASS_OVERRIDE", "test-ios-device-override"
    )
    monkeypatch.setattr("midscene.ios.agent.IOSDevice", FakeDevice)
    monkeypatch.setattr(
        "midscene.ios.agent.importlib.import_module",
        lambda name: SimpleNamespace(default=FakeDevice),
    )

    await agent_from_web_driver_agent({"modelConfig": MODEL_CONFIG})

    assert len(FakeDevice.instances) == 1
    FakeDevice.instances[0].connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_throw_clear_error_when_override_package_is_missing():
    """should throw clear error when override package is missing"""

    with pytest.raises(
        RuntimeError, match="Failed to load iOS device class override"
    ):
        await agent_from_web_driver_agent(
            {
                "modelConfig": MODEL_CONFIG,
                "iOSDeviceClassOverride": "missing-ios-device-override-package",
            }
        )
