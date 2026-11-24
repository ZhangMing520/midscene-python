"""Synced from upstream packages/core/tests/unit-test/model-adapter/auto-glm/
locate.test.ts."""

from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.ai_model.models.auto_glm.locate import (
    create_auto_glm_planning_tap_locator,
)
from midscene.core.ai_model.models.registry import get_model_runtime
from midscene.core.ai_model.workflows import ai_locate_element
from midscene.core.types import Size, UIContext
from tests.core_helpers import make_empty_tree

AUTO_GLM_LOCATE_CALL = (
    "midscene.core.ai_model.workflows.grounding.planning_action_locate."
    "call_ai_with_string_response"
)

UI_CONTEXT = UIContext(
    screenshot_base64="data:image/png;base64,AA==",
    size=Size(width=1000, height=800),
    content=[],
    tree=make_empty_tree(),
    shrunk_shot_to_logical_ratio=1,
)


def _create_locate_options():
    runtime = get_model_runtime(
        {
            "modelName": "auto-glm-test-model",
            "modelFamily": "auto-glm",
            "modelDescription": "auto-glm-test-model",
            "intent": "default",
            "slot": "default",
            "retryCount": 0,
            "retryInterval": 0,
        }
    )
    assert runtime.adapter.locate_kind == "custom"
    return runtime


def _texts(message):
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
    return []


def _has_text(message, needle):
    return any(needle in text for text in _texts(message))


def _has_image(message, url):
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("type") == "image"
        and item.get("url") == url
        for item in content
    )


def test_selects_locate_prompt_by_language_mode():
    """selects locate prompt by language mode"""
    assert "你的目标是定位并点击用户指定的UI元素" in (
        create_auto_glm_planning_tap_locator(False)["build_system_prompt"]()
    )
    assert "Your goal is to locate and tap the UI element specified by the user" in (
        create_auto_glm_planning_tap_locator(True)["build_system_prompt"]()
    )


def test_extracts_the_complete_pixel_result_from_the_first_tap_action_only():
    """extracts the complete pixel result from the first Tap action only"""
    locator = create_auto_glm_planning_tap_locator(False)
    get_located_pixel_result = locator["get_located_pixel_result"]

    assert get_located_pixel_result(
        [
            {"type": "Scroll", "param": {}},
            {
                "type": "Tap",
                "param": {
                    "locate": {
                        "locatedPixelResult": {
                            "center": [20, 30],
                            "rect": {
                                "left": 10,
                                "top": 20,
                                "width": 21,
                                "height": 21,
                            },
                        }
                    }
                },
            },
        ]
    ) == {
        "center": [20, 30],
        "rect": {"left": 10, "top": 20, "width": 21, "height": 21},
    }
    assert get_located_pixel_result([{"type": "Scroll", "param": {}}]) is None


@pytest.mark.asyncio
async def test_runs_auto_glm_custom_locate_and_maps_normalized_coordinates_to_a_point():
    """runs Auto-GLM custom locate and maps normalized coordinates to a point"""
    call = AsyncMock(
        return_value={
            "content": (
                "<think>Found submit</think><answer>"
                'do(action="Tap", element=[500,500])</answer>'
            ),
            "usage": {"total_tokens": 8},
        }
    )

    with patch(AUTO_GLM_LOCATE_CALL, new=call):
        result = await ai_locate_element(
            target_element_description="submit button",
            context=UI_CONTEXT,
            model_runtime=_create_locate_options(),
        )

    messages = call.call_args.args[0]
    assert any(message.get("role") == "system" for message in messages)
    assert any(
        message.get("role") == "user" and _has_text(message, "Tap: submit button")
        for message in messages
    )

    element = result["parse_result"]["element"]
    assert list(element["center"]) == [500, 400]
    assert result["parse_result"]["errors"] == []
    assert "rect" not in element
    assert "Found submit" in result["reasoning_content"]
    assert result["usage"] == {"total_tokens": 8}


@pytest.mark.asyncio
async def test_uses_search_area_image_size_for_planning_and_maps_the_point_back_to_the_original_screenshot():
    """uses search area image size for planning and maps the point back to the original screenshot"""
    call = AsyncMock(
        return_value={
            "content": (
                "<think>Found item in crop</think><answer>"
                'do(action="Tap", element=[500,500])</answer>'
            )
        }
    )
    search_config = {
        "source_rect": {"left": 200, "top": 100, "width": 300, "height": 200},
        "image": {
            "imageBase64": "data:image/png;base64,CROP==",
            "width": 300,
            "height": 200,
        },
        "mapping": {"offset": {"x": 200, "y": 100}, "scale": 1},
    }

    with patch(AUTO_GLM_LOCATE_CALL, new=call):
        result = await ai_locate_element(
            target_element_description="item",
            context=UI_CONTEXT,
            model_runtime=_create_locate_options(),
            search_config=search_config,
        )

    messages = call.call_args.args[0]
    assert any(
        message.get("type") == "input-message"
        and message["message"].get("role") == "user"
        and _has_image(message["message"], "data:image/png;base64,CROP==")
        for message in messages
    )
    assert list(result["parse_result"]["element"]["center"]) == [350, 200]


@pytest.mark.asyncio
async def test_returns_parse_errors_from_auto_glm_custom_locate_responses():
    """returns parse errors from Auto-GLM custom locate responses"""
    call = AsyncMock(
        return_value={"content": 'do(action="Swipe", start=[100,200], end=[300,400])'}
    )

    with patch(AUTO_GLM_LOCATE_CALL, new=call):
        result = await ai_locate_element(
            target_element_description="submit button",
            context=UI_CONTEXT,
            model_runtime=_create_locate_options(),
        )

    assert "rect" not in result
    assert result["parse_result"]["element"] is None
    assert result["parse_result"]["errors"] == [
        "No locatedPixelResult found in planner response"
    ]


@pytest.mark.asyncio
async def test_appends_reference_image_messages_for_multimodal_locate_prompts():
    """appends reference image messages for multimodal locate prompts"""
    call = AsyncMock(
        return_value={
            "content": (
                "<think>Found matching icon</think><answer>"
                'do(action="Tap", element=[500,500])</answer>'
            )
        }
    )

    with patch(AUTO_GLM_LOCATE_CALL, new=call):
        await ai_locate_element(
            target_element_description={
                "prompt": "matching icon",
                "images": [
                    {
                        "name": "target",
                        "url": "data:image/png;base64,REFERENCE==",
                    }
                ],
            },
            context=UI_CONTEXT,
            model_runtime=_create_locate_options(),
        )

    messages = call.call_args.args[0]
    assert any(
        message.get("role") == "user" and _has_text(message, "reference images")
        for message in messages
    )
    assert any(
        message.get("role") == "user"
        and _has_text(message, "reference image named 'target'")
        for message in messages
    )
    assert any(
        message.get("role") == "user"
        and _has_image(message, "data:image/png;base64,REFERENCE==")
        for message in messages
    )
