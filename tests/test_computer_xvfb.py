"""Tests for the Xvfb helper (upstream computer/xvfb.ts)."""

import os
import sys

import pytest

from midscene.computer import xvfb
from midscene.computer.device import ComputerDevice


class _FakeProcess:
    def __init__(self, pid=4321, exit_code=None):
        self.pid = pid
        self._exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self._exit_code

    def terminate(self):
        self.terminated = True


def test_needs_xvfb_only_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert xvfb.needs_xvfb(True) is True
    assert xvfb.needs_xvfb(False) is False
    assert xvfb.needs_xvfb(None) is False

    monkeypatch.setattr(sys, "platform", "darwin")
    assert xvfb.needs_xvfb(True) is False


def test_find_available_display(tmp_path, monkeypatch):
    monkeypatch.setattr(xvfb, "XVFB_LOCK_DIR", str(tmp_path))
    (tmp_path / ".X99-lock").touch()
    (tmp_path / ".X100-lock").touch()
    assert xvfb.find_available_display() == 101


def test_check_xvfb_installed(monkeypatch):
    monkeypatch.setattr(xvfb.shutil, "which", lambda name: "/usr/bin/Xvfb")
    assert xvfb.check_xvfb_installed() is True
    monkeypatch.setattr(xvfb.shutil, "which", lambda name: None)
    assert xvfb.check_xvfb_installed() is False


def test_start_xvfb_passes_display_and_resolution(monkeypatch):
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(xvfb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(xvfb.time, "sleep", lambda _seconds: None)

    instance = xvfb.start_xvfb({"resolution": "1280x720x24", "displayNumber": 108})

    assert captured["args"][:2] == ["Xvfb", ":108"]
    assert "1280x720x24" in captured["args"]
    assert captured["kwargs"]["stdin"] is xvfb.subprocess.DEVNULL
    assert instance.display == ":108"

    instance.stop()
    assert instance.process.terminated is True


def test_start_xvfb_rejects_immediate_exit(monkeypatch):
    monkeypatch.setattr(
        xvfb.subprocess, "Popen", lambda *a, **k: _FakeProcess(exit_code=1)
    )
    monkeypatch.setattr(xvfb.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="exited unexpectedly"):
        xvfb.start_xvfb({"displayNumber": 109})


def test_schedule_xvfb_stop_is_detached(monkeypatch):
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProcess(pid=999)

    monkeypatch.setattr(xvfb.subprocess, "Popen", fake_popen)
    instance = xvfb.XvfbInstance(process=_FakeProcess(pid=1234), display=":99")

    monitor = xvfb.schedule_xvfb_stop_after_process_exit(instance, parent_pid=777)

    assert monitor.pid == 999
    assert captured["args"][-2:] == ["777", "1234"]
    assert captured["kwargs"]["start_new_session"] is True


def test_signal_cleanup_respects_active_waiter(monkeypatch):
    calls = []
    handler = xvfb.create_xvfb_signal_cleanup(lambda: calls.append("cleaned"))

    monkeypatch.setattr(
        xvfb, "has_active_cli_interrupt_waiter", lambda source=None: True
    )
    handler()
    assert calls == []

    monkeypatch.setattr(
        xvfb, "has_active_cli_interrupt_waiter", lambda source=None: False
    )
    handler()
    assert calls == ["cleaned"]


def test_headless_device_requires_xvfb(monkeypatch):
    monkeypatch.setattr("midscene.computer.device.needs_xvfb", lambda _opt: True)
    monkeypatch.setattr(
        "midscene.computer.device.check_xvfb_installed", lambda: False
    )
    monkeypatch.delenv("DISPLAY", raising=False)

    with pytest.raises(RuntimeError, match="requires Xvfb"):
        ComputerDevice(headless=True)


def test_headless_device_starts_and_restores_display(monkeypatch):
    stopped = []
    instance = xvfb.XvfbInstance(process=_FakeProcess(), display=":101")
    instance.stop = lambda: stopped.append(True)  # type: ignore[method-assign]

    monkeypatch.setattr("midscene.computer.device.needs_xvfb", lambda _opt: True)
    monkeypatch.setattr(
        "midscene.computer.device.check_xvfb_installed", lambda: True
    )
    monkeypatch.setattr(
        "midscene.computer.device.start_xvfb", lambda: instance
    )
    monkeypatch.delenv("DISPLAY", raising=False)

    device = ComputerDevice(headless=True)
    try:
        assert os.environ["DISPLAY"] == ":101"
    finally:
        device.close()

    assert stopped == [True]
    assert "DISPLAY" not in os.environ
