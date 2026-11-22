"""Port of upstream packages/harmony/tests/unit-test/hdc.test.ts.

Only the cases covered by the former aggregate ``tests/test_harmony.py`` are
kept: HDC exec argument building, click coordinate validation, keyEvent
validation and clearTextField. App-launches, screen-info parsing and
listTargets are not part of the aggregate coverage.
"""

import re
from unittest.mock import AsyncMock

import pytest

from midscene.harmony.hdc import HdcClient


class FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.returncode = returncode
        self.communicate = AsyncMock(
            return_value=(stdout.encode(), stderr.encode())
        )


@pytest.fixture
def hdc_calls(monkeypatch):
    calls = []

    def install(stdout: str = "output", stderr: str = "", returncode: int = 0):
        async def fake(*args, **_kwargs):
            calls.append(list(args))
            return FakeProcess(stdout, stderr, returncode)

        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake
        )

    install.calls = calls
    install()
    return install


@pytest.mark.asyncio
async def test_should_execute_hdc_command_without_device_id(hdc_calls):
    """should execute hdc command without device id."""

    hdc = HdcClient()

    result = await hdc.exec(["list", "targets"])

    assert result == "output"
    assert hdc_calls.calls == [["hdc", "list", "targets"]]


@pytest.mark.asyncio
async def test_should_include_t_flag_when_device_id_is_specified(hdc_calls):
    """should include -t flag when device id is specified."""

    hdc = HdcClient(device_id="em-1")

    await hdc.exec(["shell", "ls"])

    assert hdc_calls.calls == [["hdc", "-t", "em-1", "shell", "ls"]]


@pytest.mark.asyncio
async def test_should_reject_a_non_finite_coordinate_before_invoking_hdc(hdc_calls):
    """should reject a non-finite coordinate before invoking HDC.

    Upstream's message is "HDC x coordinate must be a non-negative finite
    number"; the Python client validates in ``round_ui_coordinate`` and raises
    ValueError before spawning the process.
    """

    hdc = HdcClient()

    with pytest.raises(ValueError, match="coordinate"):
        await hdc.click(float("nan"), 200)

    assert hdc_calls.calls == []


@pytest.mark.asyncio
async def test_should_execute_numeric_and_supported_system_key_events(hdc_calls):
    """should execute numeric and supported system key events."""

    hdc = HdcClient()

    await hdc.key_event("2072", "2038")
    await hdc.key_event("Home")

    assert hdc_calls.calls == [
        ["hdc", "shell", "uitest uiInput keyEvent 2072 2038"],
        ["hdc", "shell", "uitest uiInput keyEvent Home"],
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["RecentApps", "F5", "Control+A", ";"])
async def test_should_reject_unsupported_string_key_before_invoking_hdc(
    key, hdc_calls
):
    """should reject unsupported string key %s before invoking HDC."""

    hdc = HdcClient()

    with pytest.raises(RuntimeError, match=f"Invalid HDC key event: {re.escape(key)}"):
        await hdc.key_event(key)

    assert hdc_calls.calls == []


@pytest.mark.asyncio
async def test_should_reject_an_empty_key_event(hdc_calls):
    """should reject an empty key event."""

    hdc = HdcClient()

    with pytest.raises(
        RuntimeError, match="HDC keyEvent requires between 1 and 3 keys"
    ):
        await hdc.key_event()

    assert hdc_calls.calls == []


@pytest.mark.asyncio
async def test_should_reject_more_than_three_key_events(hdc_calls):
    """should reject more than three key events."""

    hdc = HdcClient()

    with pytest.raises(
        RuntimeError, match="HDC keyEvent requires between 1 and 3 keys"
    ):
        await hdc.key_event("1", "2", "3", "4")

    assert hdc_calls.calls == []


@pytest.mark.asyncio
async def test_should_reject_combining_a_system_key_with_another_key(hdc_calls):
    """should reject combining a system key with another key."""

    hdc = HdcClient()

    with pytest.raises(
        RuntimeError, match="HDC system key events cannot be combined"
    ):
        await hdc.key_event("Home", "2054")

    assert hdc_calls.calls == []


@pytest.mark.asyncio
async def test_should_select_all_with_ctrl_a_and_delete_in_one_shell_call(hdc_calls):
    """should select all with Ctrl+A and delete in one shell call."""

    hdc = HdcClient()

    await hdc.clear_text_field()

    assert len(hdc_calls.calls) == 1
    assert hdc_calls.calls[0] == [
        "hdc",
        "shell",
        "uitest uiInput keyEvent 2072 2017;uitest uiInput keyEvent 2055",
    ]
