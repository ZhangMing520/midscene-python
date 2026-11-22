"""Port of upstream packages/computer/tests/unit-test/input-driver-scroll.test.ts.

Upstream exercises ``ComputerInputDriver.emitScrollDetents`` on the libnut
driver. The Python driver is pyautogui-backed, but the same contract holds:
one wheel event per detent, aimed at the target point.
"""

import sys
from typing import List
from unittest.mock import MagicMock

import pytest


class FakePyAutoGUI:
    def __init__(self):
        self.calls: List[tuple] = []
        self.size_result = MagicMock(width=1920, height=1080)

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "size":
                return self.size_result
            return None

        return record


@pytest.fixture
def fake_pyautogui(monkeypatch):
    fake = FakePyAutoGUI()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.fixture
def fast_wheel(monkeypatch):
    from midscene.computer import input_driver

    monkeypatch.setattr(input_driver, "_DETENT_DELAY", 0)


def _device(**options):
    from midscene.computer.device import ComputerDevice

    return ComputerDevice(**options)


def _calls(fake, name):
    return [c for c in fake.calls if c[0] == name]


@pytest.mark.asyncio
async def test_emits_one_libnut_scrollmouse_call_per_detent(
    fake_pyautogui, fast_wheel
):
    """emits one libnut.scrollMouse call per detent.

    The pyautogui driver emits one wheel call per 100 px detent instead of
    libnut's ``scrollMouse(dx, dy)``; 500 px is therefore five detents.
    """

    from midscene.computer.input_driver import detent_count

    await _device().scroll("down", 500)

    scrolls = _calls(fake_pyautogui, "scroll")
    assert len(scrolls) == detent_count(500) == 5
    for call in scrolls:
        assert call[1] == (-1, 960, 540)


def test_edge_scroll_fallback_aims_for_the_full_boundary_distance():
    """edge-scroll fallback aims for the full boundary distance.

    Regression: edge scrolls used to be wired to a small repeat count, which
    at 100 px/detent stopped long pages far short of the top/bottom.
    """

    from midscene.computer.input_driver import (
        _EDGE_SCROLL_TOTAL_PX,
        detent_count,
    )

    assert detent_count(_EDGE_SCROLL_TOTAL_PX) >= 200
