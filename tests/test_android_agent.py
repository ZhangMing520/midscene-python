"""Port of upstream ``packages/android/tests/unit-test/agent.test.ts``.

Node-only Test Runner platform nodes and the ``exposeRunAdbShellAction``
filter are not part of the Python runtime; the remaining cases exercise the
ported agent wrappers and ``agentFromAdbDevice``.
"""

from unittest.mock import AsyncMock

import pytest

from midscene.android.agent import AndroidAgent, agent_from_adb_device
from midscene.android.device import AndroidDevice

MODEL_CONFIG = {
    "MIDSCENE_MODEL_NAME": "mock",
    "MIDSCENE_MODEL_API_KEY": "mock",
    "MIDSCENE_MODEL_BASE_URL": "mock",
    "MIDSCENE_MODEL_FAMILY": "doubao-vision",
}


def test_declares_common_and_android_test_runner_nodes():
    """declares common and Android Test Runner Nodes"""
    names = [
        node.name for node in AndroidAgent.get_test_runner_node_definitions()
    ]
    assert len(names) > 0
    assert len(set(names)) == len(names)


class TestAndroidAgent:
    def test_should_create_android_agent_successfully(self):
        """should create AndroidAgent successfully"""
        agent = AndroidAgent(
            AndroidDevice("test-device"),
            {"modelConfig": MODEL_CONFIG},
        )
        assert isinstance(agent, AndroidAgent)

    @pytest.mark.asyncio
    async def test_should_call_page_launch_with_the_given_uri(self):
        """should call page.launch with the given uri"""
        device = AndroidDevice("test-device")
        device.launch_app = AsyncMock()
        agent = AndroidAgent(device, {"modelConfig": MODEL_CONFIG})

        await agent.launch("https://example.com")

        device.launch_app.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_should_call_page_terminate_with_the_given_uri(self):
        """should call page.terminate with the given uri"""
        device = AndroidDevice("test-device")
        device.stop_app = AsyncMock()
        agent = AndroidAgent(device, {"modelConfig": MODEL_CONFIG})

        await agent.terminate("com.android.settings")

        device.stop_app.assert_awaited_once_with("com.android.settings")

    @pytest.mark.asyncio
    async def test_should_pass_timeout_options_through_the_run_adb_shell_action(self):
        """should pass timeout options through the RunAdbShell action"""
        device = AndroidDevice("test-device")
        device.run_adb_shell = AsyncMock(return_value="adb-result")
        agent = AndroidAgent(device, {"modelConfig": MODEL_CONFIG})

        result = await agent.run_adb_shell("sleep 2", {"timeout": 2000})

        assert result == "adb-result"
        device.run_adb_shell.assert_awaited_once_with(
            "sleep 2", timeout=2000.0
        )

    @pytest.mark.skip(
        reason="Python filters the action space by device primitive support; "
        "there is no exposeRunAdbShellAction device option"
    )
    @pytest.mark.asyncio
    async def test_should_reject_explicit_calls_when_run_adb_shell_is_hidden(self):
        """should reject explicit calls when RunAdbShell is hidden"""


class TestAgentFromAdbDevice:
    @pytest.mark.asyncio
    async def test_should_use_the_first_device_and_forward_adb_options_if_no_device_id_is_provided(
        self, monkeypatch
    ):
        """should use the first device and forward ADB options if no deviceId is provided"""
        mock_devices = [{"udid": "device-1"}, {"udid": "device-2"}]
        get_devices = AsyncMock(return_value=mock_devices)
        monkeypatch.setattr(
            "midscene.android.agent.get_connected_devices", get_devices
        )

        created = {}

        class FakeDevice:
            interface_type = "android"

            def __init__(self, device_id, options=None):
                created["device_id"] = device_id
                created["options"] = options
                self.connect = AsyncMock()

            def set_app_name_mapping(self, mapping):
                created["mapping"] = mapping

        monkeypatch.setattr("midscene.android.agent.AndroidDevice", FakeDevice)

        options = {
            "androidAdbPath": "/custom/platform-tools/adb",
            "remoteAdbHost": "localhost",
            "remoteAdbPort": 5038,
        }
        agent = await agent_from_adb_device(None, options)

        get_devices.assert_awaited_once_with(options)
        assert created["device_id"] == "device-1"
        assert created["options"] == options
        assert created["mapping"]
        assert isinstance(agent, AndroidAgent)

    @pytest.mark.asyncio
    async def test_should_use_the_specified_device_id(self, monkeypatch):
        """should use the specified deviceId"""
        created = {}

        class FakeDevice:
            interface_type = "android"

            def __init__(self, device_id, options=None):
                created["device_id"] = device_id
                created["options"] = options
                self.connect = AsyncMock()

            def set_app_name_mapping(self, mapping):
                created["mapping"] = mapping

        monkeypatch.setattr("midscene.android.agent.AndroidDevice", FakeDevice)

        agent = await agent_from_adb_device("test-device-id")

        assert created["device_id"] == "test-device-id"
        assert isinstance(agent, AndroidAgent)

    @pytest.mark.asyncio
    async def test_should_pass_options_to_android_device(self, monkeypatch):
        """should pass options to AndroidDevice"""
        created = {}

        class FakeDevice:
            interface_type = "android"

            def __init__(self, device_id, options=None):
                created["device_id"] = device_id
                created["options"] = options
                self.connect = AsyncMock()

            def set_app_name_mapping(self, mapping):
                created["mapping"] = mapping

        monkeypatch.setattr("midscene.android.agent.AndroidDevice", FakeDevice)

        options = {
            "autoDismissKeyboard": False,
            "androidAdbPath": "/path/to/adb",
            "remoteAdbHost": "localhost",
            "remoteAdbPort": 5037,
            "imeStrategy": "yadb-for-non-ascii",
        }

        await agent_from_adb_device("test-device-id", options)

        assert created["device_id"] == "test-device-id"
        assert created["options"] == options

    @pytest.mark.asyncio
    async def test_should_throw_when_no_android_devices_are_connected(self, monkeypatch):
        """throws a clear error when no Android device is connected"""
        monkeypatch.setattr(
            "midscene.android.agent.get_connected_devices",
            AsyncMock(return_value=[]),
        )

        with pytest.raises(RuntimeError, match="No Android devices found"):
            await agent_from_adb_device()
