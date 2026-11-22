"""Port of upstream packages/computer/tests/unit-test/device.test.ts.

Only the cases covered by the former aggregate ``tests/test_computer.py`` are
kept. The Python backend captures with pyautogui, so upstream's multi-display
selection has no equivalent and the case is skipped with that reason.
"""

import asyncio

import pytest

from midscene.computer import device as device_module
from midscene.computer.device import (
    LIBNUT_FALLBACK_EDGE_DETENTS,
    ComputerDevice,
    get_display_info_binary,
    get_phased_scroll_binary,
    map_display_local_point_to_global,
    read_darwin_display_geometries,
    resolve_darwin_display_geometry_from_list,
    run_phased_scroll,
)
from midscene.core.device import build_action_space_for


def test_should_have_action_space():
    """should have action space."""

    device = ComputerDevice()
    actions = build_action_space_for(device.interface_type.value)
    action_names = [action.name for action in actions]

    assert len(action_names) > 0
    assert "Tap" in action_names
    assert "Input" in action_names
    assert "Scroll" in action_names
    assert "KeyboardPress" in action_names
    # Mouse actions, including Hover (aiHover) — see issue #2413
    assert "Hover" in action_names
    assert "DoubleClick" in action_names
    assert "RightClick" in action_names
    assert "MiddleClick" in action_names
    assert "DragAndDrop" in action_names
    assert "Swipe" in action_names
    # The desktop backend has no two-finger touch surface.
    assert "Pinch" not in action_names


@pytest.mark.skip(
    reason=(
        "Python's pyautogui backend captures the primary display only and "
        "ComputerDevice rejects display_id with NotImplementedError"
    )
)
def test_should_create_device_with_display_id():
    """should create device with display id."""

    ComputerDevice(display_id="test-display")


def test_libnut_fallback_edge_detents_matches_upstream_constant():
    """caps the libnut fallback at the upstream edge-scroll budget."""
    assert LIBNUT_FALLBACK_EDGE_DETENTS == 200


def test_display_helpers_are_unavailable_off_darwin(monkeypatch):
    monkeypatch.setattr(device_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(device_module, "_display_info_binary_path", None)
    monkeypatch.setattr(device_module, "_phased_scroll_binary_path", None)

    assert get_display_info_binary() is None
    assert get_phased_scroll_binary() is None
    assert read_darwin_display_geometries() == []
    assert run_phased_scroll("down", 300, 5) is False


def _fake_helper(tmp_path, name, body, mode=0o755):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return str(path)


def test_reads_and_filters_darwin_display_geometries(tmp_path, monkeypatch):
    helper = _fake_helper(
        tmp_path,
        "display-info",
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'displays': ["
        "{'screenIndex': 0, 'cgDisplayId': 1, 'primary': True, "
        "'bounds': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}},"
        "{'screenIndex': 1, 'primary': False},"
        "{'screenIndex': 2, 'cgDisplayId': 3, 'primary': False, "
        "'bounds': {'x': float('inf'), 'y': 0, 'width': 1, 'height': 1}}"
        "]}))\n",
    )
    monkeypatch.setattr(
        device_module, "get_display_info_binary", lambda: helper
    )

    displays = read_darwin_display_geometries()

    assert len(displays) == 1
    assert displays[0]["screenIndex"] == 0
    assert displays[0]["primary"] is True


def test_rejects_unparseable_display_info_output(tmp_path, monkeypatch):
    helper = _fake_helper(
        tmp_path, "display-info", "#!/usr/bin/env python3\nprint('not json')\n"
    )
    monkeypatch.setattr(
        device_module, "get_display_info_binary", lambda: helper
    )

    assert read_darwin_display_geometries() == []


def test_resolves_darwin_display_geometry_by_primary_index_and_cg_id():
    displays = [
        {
            "screenIndex": 0,
            "cgDisplayId": 10,
            "primary": False,
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
        {
            "screenIndex": 1,
            "cgDisplayId": 20,
            "primary": True,
            "bounds": {"x": 100, "y": 0, "width": 100, "height": 100},
        },
    ]

    assert resolve_darwin_display_geometry_from_list(None, displays) is displays[1]
    assert resolve_darwin_display_geometry_from_list("0", displays) is displays[0]
    assert resolve_darwin_display_geometry_from_list("10", displays) is displays[0]
    for invalid in ("abc", "1.5", "-1", ""):
        if invalid == "":
            assert resolve_darwin_display_geometry_from_list(invalid, displays) is displays[1]
        else:
            assert resolve_darwin_display_geometry_from_list(invalid, displays) is None
    assert resolve_darwin_display_geometry_from_list("7", displays) is None
    assert resolve_darwin_display_geometry_from_list("0", []) is None


def test_maps_display_local_points_to_global_coordinates():
    geometry = {
        "bounds": {"x": 1920, "y": -200, "width": 1920, "height": 1080}
    }

    assert map_display_local_point_to_global({"x": 10, "y": 20}, geometry) == {
        "x": 1930,
        "y": -180,
    }
    point = {"x": 10, "y": 20}
    assert map_display_local_point_to_global(point) is point


def test_run_phased_scroll_reports_helper_exit_status(tmp_path, monkeypatch):
    success = _fake_helper(
        tmp_path, "phased-scroll-ok", "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n"
    )
    failure = _fake_helper(
        tmp_path, "phased-scroll-fail", "#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n"
    )

    monkeypatch.setattr(device_module, "_phased_scroll_exec_warned", False)
    monkeypatch.setattr(device_module, "get_phased_scroll_binary", lambda: success)
    assert run_phased_scroll("down", 240, 4) is True

    monkeypatch.setattr(device_module, "get_phased_scroll_binary", lambda: failure)
    assert run_phased_scroll("down", 240, 4) is False


def test_describe_and_url_match_upstream_contract():
    device = ComputerDevice()

    assert device.describe() == "Computer Device"
    assert asyncio.run(device.url()) == ""
