"""Coverage for ported core root modules."""

import pytest

from midscene.core.common import (
    build_yaml_flow_from_plans,
    dump_action_param,
    get_readable_time_string,
    parse_action_param,
    user_prompt_to_multimodal_prompt,
)
from midscene.core.device import DeviceAction
from midscene.core.screenshot_item import (
    ScreenshotItem,
    extract_image_by_id_sync,
    normalize_screenshot_ref,
)
from midscene.core.skill import SkillMidsceneTools, _run_command, report_cli_error
from midscene.core.task_runner import (
    TaskExecutionError,
    TaskRunner,
    serialize_error,
    truncate_serialized_error_string,
)
from midscene.core.utils import (
    anti_escape_script_tag,
    escape_script_tag,
    insert_content_before_closing_html,
    process_cache_config,
    report_html_content,
)


def test_process_cache_config_resolution():
    assert process_cache_config(False, "id") is False
    assert process_cache_config(True, "id") == {"id": "id"}
    assert process_cache_config({"path": "./c"}, "id") == {"path": "./c", "id": "id"}
    assert process_cache_config({"id": "kept"}, "id") == {"id": "kept"}
    assert process_cache_config(None, "id") is None


def test_script_escape_round_trip():
    escaped = escape_script_tag("<script>alert(1)</script>")
    assert "<" not in escaped and ">" not in escaped
    assert anti_escape_script_tag(escaped) == "<script>alert(1)</script>"


def test_html_content_helpers():
    html = "<html><body></body></html>"
    assert insert_content_before_closing_html(html, "X").endswith("X\n</html>")
    content = report_html_content('{"a": 1}', with_tpl=False)
    assert 'type="midscene_web_dump"' in content
    assert '"a": 1' in content


def test_dump_action_param_flattens_locator_fields():
    action = DeviceAction(
        name="Tap",
        description="",
        locate_fields=["locate"],
        interface_alias="aiTap",
    )
    assert dump_action_param({"locate": {"prompt": "login"}}, action) == {
        "locate": "login"
    }
    prompt = {"prompt": "login", "images": [{"name": "a", "url": "b"}]}
    assert dump_action_param({"locate": {"prompt": prompt}}, action) == {
        "locate": "login (with 1 image)"
    }


def test_parse_action_param_scales_model_distances():
    action = DeviceAction(name="Scroll", description="", distance_fields=["distance"])
    parsed = parse_action_param(
        {"distance": 100},
        action,
        {"distanceUnit": "model-input-image-pixel", "shrunkShotToLogicalRatio": 2},
    )
    assert parsed == {"distance": 50}
    assert parse_action_param({"x": 1}, None) is None


def test_build_yaml_flow_from_plans_inlines_shortcuts():
    tap = DeviceAction(
        name="Tap",
        description="",
        param_schema={"locate": {}},
        locate_fields=["locate"],
        interface_alias="aiTap",
    )
    launch = DeviceAction(
        name="Launch",
        description="",
        param_schema={"uri": {}},
        interface_alias="launch",
    )
    flow = build_yaml_flow_from_plans(
        [
            {"type": "Tap", "param": {"locate": {"prompt": "login"}}},
            {"type": "Launch", "param": {"uri": "app://x"}},
        ],
        [tap, launch],
    )
    assert flow[0] == {"aiTap": "", "locate": "login"}
    assert flow[1] == {"launch": "app://x"}


def test_prompt_and_time_helpers():
    assert user_prompt_to_multimodal_prompt("hi") is None
    assert user_prompt_to_multimodal_prompt({"prompt": "hi"}) is None
    assert user_prompt_to_multimodal_prompt(
        {"prompt": "hi", "images": [{"name": "a", "url": "b"}]}
    ) == {"images": [{"name": "a", "url": "b"}], "convertHttpImage2Base64": False}
    assert get_readable_time_string("YYYY-MM-DD", 0).endswith("(YYYY-MM-DD)")


def test_screenshot_item_serialization_and_recovery(tmp_path):
    item = ScreenshotItem.create("data:image/jpeg;base64,AAA", 123)
    assert item.format == "jpeg"
    assert item.extension == "jpeg"
    assert item.raw_base64 == "AAA"
    ref = item.to_serializable()
    assert ref["type"] == "midscene_screenshot_ref"
    assert ScreenshotItem.is_serialized(ref)
    assert normalize_screenshot_ref(ref) == ref
    assert normalize_screenshot_ref({"type": "nope"}) is None

    html = tmp_path / "report.html"
    html.write_text(
        '<script type="midscene-image" data-id="abc">'
        "__midscene_lt__svg__midscene_gt__"
        "</script>",
        encoding="utf-8",
    )
    assert extract_image_by_id_sync(str(html), "abc") == "<svg>"

    persisted = ScreenshotItem.create("data:image/png;base64,AAA", 1)
    persisted_id = persisted.id
    inline_path = tmp_path / "inline.html"
    inline_path.write_text(
        f'<script type="midscene-image" data-id="{persisted_id}">'
        "data:image/png;base64,BBB"
        "</script>",
        encoding="utf-8",
    )
    persisted.mark_persisted_inline(str(inline_path))
    assert persisted.has_base64() is False
    assert persisted.base64 == "data:image/png;base64,BBB"


def test_serialize_error_bounds_and_fields():
    error = RuntimeError("x" * 5000)
    error.code = "E_CODE"  # type: ignore[attr-defined]
    serialized = serialize_error(error)
    assert serialized["name"] == "RuntimeError"
    assert serialized["code"] == "E_CODE"
    assert serialized["message"].endswith("[truncated]")
    assert truncate_serialized_error_string("short") == "short"
    assert serialize_error("boom") == {"name": "NonError", "message": "boom"}


@pytest.mark.asyncio
async def test_task_runner_success_and_dump():
    async def build_context(signal=None):
        return {"screenshot_base64": "data:image/png;base64,AAA"}

    async def executor(ctx):
        return {"thought": "ok", "output": 123}

    runner = TaskRunner("exec", build_context)
    result = await runner.append_and_flush(
        {"type": "Insight", "subType": "Query", "executor": executor}
    )
    assert result == {"thought": "ok", "output": 123}
    assert runner.status == "completed"
    dump = runner.dump()
    assert dump["tasks"][0]["status"] == "finished"
    assert dump["tasks"][0]["recorder"][0]["timing"] == "after-calling"


@pytest.mark.asyncio
async def test_task_runner_failure_raises_task_execution_error():
    async def build_context(signal=None):
        return None

    async def boom(ctx):
        raise RuntimeError("kaboom")

    runner = TaskRunner("exec", build_context)
    with pytest.raises(TaskExecutionError) as raised:
        await runner.append_and_flush(
            {"type": "Insight", "subType": "Query", "executor": boom}
        )
    assert raised.value.code == "TASK_EXECUTION_FAILED"
    assert runner.status == "error"
    assert runner.latest_error_task()["errorMessage"] == "kaboom"


@pytest.mark.asyncio
async def test_task_runner_append_error_plan_records_failure():
    async def build_context(signal=None):
        return None

    runner = TaskRunner("exec", build_context)
    with pytest.raises(TaskExecutionError):
        await runner.append_error_plan("plan failed")
    assert runner.tasks[0]["subType"] == "Error"
    assert runner.tasks[0]["errorMessage"] == "plan failed"


@pytest.mark.asyncio
async def test_skill_command_dispatch():
    class FakeAgent:
        async def ai_act(self, prompt):
            return f"acted:{prompt}"

    assert await _run_command(FakeAgent(), "act", {"prompt": "go"}) == "acted:go"
    with pytest.raises(ValueError):
        await _run_command(FakeAgent(), "unknown", {})


def test_skill_tools_lazy_device():
    class Device:
        pass

    tools = SkillMidsceneTools(Device)
    assert isinstance(tools.create_temporary_device(), Device)
    assert report_cli_error(RuntimeError("x")) == 1
