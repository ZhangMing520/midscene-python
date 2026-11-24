"""Synced from upstream packages/core/tests/unit-test/agent-describe-element.test.ts.

The upstream suite constructs a real Agent with a mocked Service. The Python
port drives midscene.core.element_describer with a lightweight fake agent and
monkeypatches ``ai_describe_element`` / ``locate_service``, which is the same
seam used by the Python implementation.
"""

import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from midscene.core import element_describer
from midscene.core.element_describer import (
    describe_element_at_point,
    verify_element_description_at_point,
    verify_locator,
)

LOGICAL_SCREENSHOT_SIZE = {"width": 3282, "height": 1442}


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


_SCREENSHOT = _png(LOGICAL_SCREENSHOT_SIZE["width"], LOGICAL_SCREENSHOT_SIZE["height"])


class _FakeAgent:
    def __init__(self):
        self.runtime_requests = []

    def _resolve_runtime(self, task_type):
        self.runtime_requests.append(task_type)
        return SimpleNamespace(config={})

    async def get_context(self):
        return {"screenshot_base64": _SCREENSHOT, "size": dict(LOGICAL_SCREENSHOT_SIZE)}


def _agent():
    return _FakeAgent()


@pytest.fixture
def describe_calls(monkeypatch):
    calls = []

    async def fake_describe(context, target, runtime, deep_describe=False):
        calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "test description"}

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    return calls


@pytest.fixture
def locate_calls(monkeypatch):
    calls = []

    async def fake_locate(**kwargs):
        calls.append(kwargs)
        return {"element": {"center": [10, 10]}}

    monkeypatch.setattr(element_describer, "locate_service", fake_locate)
    return calls


@pytest.mark.asyncio
async def test_skips_locator_verification_when_verify_prompt_is_false(
    monkeypatch, describe_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "LocalSearch title"}

    async def failing_locate(**kwargs):
        raise AssertionError("should not verify locator")

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", failing_locate)

    result = await describe_element_at_point(
        _agent(), [10, 20], {"verify_prompt": False}
    )

    assert result["prompt"] == "LocalSearch title"
    assert result["deepLocate"] is False
    assert result["success"] is True
    assert result["verifyResult"] is None


@pytest.mark.asyncio
async def test_keeps_locator_verification_enabled_by_default(
    monkeypatch, describe_calls, locate_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "LocalSearch title"}

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)

    result = await describe_element_at_point(_agent(), [10, 20])

    verify_result = result["verifyResult"]
    assert verify_result["pass"] is True
    assert verify_result["center"] == [10, 10]
    assert verify_result["centerDistance"] == 10
    assert len(locate_calls) == 1


@pytest.mark.asyncio
async def test_returns_the_generated_prompt_when_locator_verification_throws(
    monkeypatch, describe_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "Missing target"}

    async def failing_locate(**kwargs):
        raise Exception("failed to locate element")

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", failing_locate)

    result = await describe_element_at_point(_agent(), [10, 20], {"retry_limit": 1})

    assert result["prompt"] == "Missing target"
    assert result["deepLocate"] is False
    assert result["success"] is False
    assert result["error"] == "failed to locate element"
    assert result["failureStage"] == "verify"
    assert result["verifyResult"] is None


@pytest.mark.asyncio
async def test_enables_deep_describe_on_the_first_retry_after_verifier_failure(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["Broad target", "Precise target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    locate_calls.clear()

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 100, "height": 100},
                "center": [50, 50],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    def locator_verify_fn(payload):
        return {
            **payload["verifyResult"],
            "pass": payload["prompt"] == "Precise target",
        }

    result = await describe_element_at_point(
        _agent(),
        [10, 10],
        {"retry_limit": 2, "locator_verify_fn": locator_verify_fn},
    )

    assert result["prompt"] == "Precise target"
    assert result["deepLocate"] is True
    assert result["deepDescribe"] is True
    assert len(describe_calls) == 2
    assert describe_calls[0]["deep"] is False
    assert describe_calls[1]["deep"] is True


@pytest.mark.asyncio
async def test_enables_deep_describe_on_retry_even_when_deep_locate_is_explicitly_false(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["Broad target", "Precise target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 100, "height": 100},
                "center": [50, 50],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await describe_element_at_point(
        _agent(),
        [10, 10],
        {
            "deep_locate": False,
            "retry_limit": 2,
            "locator_verify_fn": lambda payload: {
                **payload["verifyResult"],
                "pass": payload["prompt"] == "Precise target",
            },
        },
    )

    assert result["prompt"] == "Precise target"
    assert result["deepLocate"] is False
    assert result["deepDescribe"] is True
    assert len(describe_calls) == 2
    assert describe_calls[0]["deep"] is False
    assert describe_calls[1]["deep"] is True


@pytest.mark.asyncio
async def test_keeps_deep_describe_disabled_on_retry_when_explicitly_false(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["Broad target", "Precise target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 100, "height": 100},
                "center": [50, 50],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await describe_element_at_point(
        _agent(),
        [10, 10],
        {
            "deep_describe": False,
            "retry_limit": 2,
            "locator_verify_fn": lambda payload: {
                **payload["verifyResult"],
                "pass": payload["prompt"] == "Precise target",
            },
        },
    )

    assert result["prompt"] == "Precise target"
    assert result["deepDescribe"] is False
    assert len(describe_calls) == 2
    assert describe_calls[0]["deep"] is False
    assert describe_calls[1]["deep"] is False


@pytest.mark.asyncio
async def test_allows_locator_verify_fn_to_override_describe_element_at_point_retry_pass_criteria(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["First target", "Second target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 20, "height": 20},
                "center": [10, 10],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await describe_element_at_point(
        _agent(),
        [10, 10],
        {
            "retry_limit": 2,
            "locator_verify_fn": lambda payload: {
                **payload["verifyResult"],
                "pass": payload["prompt"] == "Second target",
            },
        },
    )

    assert result["prompt"] == "Second target"
    assert result["verifyResult"]["pass"] is True
    assert len(describe_calls) == 2


@pytest.mark.asyncio
async def test_enables_verifier_locate_deep_locate_on_retry_by_default(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["First target", "Second target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 20, "height": 20},
                "center": [10, 10],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    await describe_element_at_point(
        _agent(),
        [10, 10],
        {
            "retry_limit": 2,
            "locator_verify_fn": lambda payload: {
                **payload["verifyResult"],
                "pass": payload["prompt"] == "Second target",
            },
        },
    )

    assert len(locate_calls) == 2
    assert locate_calls[0]["deep_locate"] is False
    assert locate_calls[1]["deep_locate"] is True
    assert describe_calls[0]["deep"] is False
    assert describe_calls[1]["deep"] is True


@pytest.mark.asyncio
async def test_keeps_verifier_locate_deep_locate_disabled_on_retry_when_explicitly_false(
    monkeypatch, describe_calls, locate_calls
):
    descriptions = iter(["First target", "Second target"])

    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": next(descriptions)}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 20, "height": 20},
                "center": [10, 10],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await describe_element_at_point(
        _agent(),
        [10, 10],
        {
            "deep_locate": False,
            "retry_limit": 2,
            "locator_verify_fn": lambda payload: {
                **payload["verifyResult"],
                "pass": payload["prompt"] == "Second target",
            },
        },
    )

    assert result["deepLocate"] is False
    assert len(locate_calls) == 2
    assert locate_calls[0]["deep_locate"] is False
    assert locate_calls[1]["deep_locate"] is False


@pytest.mark.asyncio
async def test_accepts_a_distant_center_when_the_returned_rect_contains_the_target(
    monkeypatch, describe_calls, locate_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "Broad row container"}

    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 100, "height": 100},
                "center": [50, 50],
            }
        }

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)
    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await describe_element_at_point(_agent(), [10, 10], {"retry_limit": 2})

    assert result["prompt"] == "Broad row container"
    assert result["deepLocate"] is False
    assert result["verifyResult"]["pass"] is True
    assert result["verifyResult"]["rect"] == {
        "left": 0,
        "top": 0,
        "width": 100,
        "height": 100,
    }
    assert result["verifyResult"]["center"] == [50, 50]
    assert result["verifyResult"]["centerDistance"] == 57
    assert result["verifyResult"]["includedInRect"] is True
    assert result["success"] is True
    assert len(describe_calls) == 1


@pytest.mark.asyncio
async def test_rejects_a_distant_center_when_no_rect_is_returned(
    monkeypatch, locate_calls
):
    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {"element": {"center": [50, 50]}}

    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await verify_locator(_agent(), "target element", [10, 10])

    assert result["pass"] is False
    assert result["center"] == [50, 50]
    assert result["centerDistance"] == 57
    assert result["rect"] is None
    assert result["includedInRect"] is None


@pytest.mark.asyncio
async def test_keeps_locator_verification_strict_when_the_expected_point_is_outside_the_located_rect(
    monkeypatch, locate_calls
):
    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 10, "height": 10},
                "center": [5, 5],
            }
        }

    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await verify_locator(
        _agent(),
        "input text area",
        [15, 5],
        {"center_distance_threshold": 1},
    )

    assert result == {
        "pass": False,
        "rect": {"left": 0, "top": 0, "width": 10, "height": 10},
        "center": [5, 5],
        "centerDistance": 10,
        "includedInRect": False,
    }


@pytest.mark.asyncio
async def test_maps_logical_coordinates_into_screenshot_coordinates(
    monkeypatch, describe_calls, locate_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "Mapped target"}

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)

    await describe_element_at_point(
        _agent(),
        [50, 25],
        {
            "screenshot_base64": _SCREENSHOT,
            "coordinate_space": "logical",
            "logical_size": {"width": 100, "height": 50},
        },
    )

    assert describe_calls[0]["target"] == [1641, 721]
    assert locate_calls[0]["context"].size.width == 3282
    assert locate_calls[0]["context"].size.height == 1442


@pytest.mark.asyncio
async def test_requires_logical_size_when_screenshot_context_uses_logical_coordinates(
    monkeypatch, describe_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "should not run"}

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)

    with pytest.raises(
        ValueError, match="logical_size is required when coordinate_space is logical"
    ):
        await describe_element_at_point(
            _agent(),
            [50, 25],
            {
                "screenshot_base64": _SCREENSHOT,
                "coordinate_space": "logical",
            },
        )
    assert describe_calls == []


@pytest.mark.asyncio
async def test_uses_parsed_screenshot_size_when_provided_screenshot_size_differs(
    monkeypatch, describe_calls
):
    async def fake_describe(context, target, runtime, deep_describe=False):
        describe_calls.append({"target": list(target), "deep": deep_describe})
        return {"description": "Actual-size target"}

    monkeypatch.setattr(element_describer, "ai_describe_element", fake_describe)

    await describe_element_at_point(
        _agent(),
        [50, 50],
        {
            "verify_prompt": False,
            "screenshot_base64": _SCREENSHOT,
            "screenshot_size": {"width": 100, "height": 100},
            "coordinate_space": "logical",
            "logical_size": {"width": 100, "height": 100},
        },
    )

    assert describe_calls[0]["target"] == [1641, 721]


@pytest.mark.asyncio
async def test_verifies_an_explicit_element_description_without_a_screenshot_context(
    monkeypatch, locate_calls
):
    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 0, "top": 0, "width": 20, "height": 20},
                "center": [10, 10],
            }
        }

    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await verify_element_description_at_point(
        _agent(), "Submit button", [10, 10], {"center_distance_threshold": 12}
    )

    assert result["pass"] is True
    assert result["rect"] == {"left": 0, "top": 0, "width": 20, "height": 20}
    assert result["center"] == [10, 10]
    assert result["centerDistance"] == 0
    assert result["includedInRect"] is True


@pytest.mark.asyncio
async def test_verifies_an_explicit_element_description_against_a_provided_screenshot(
    monkeypatch, locate_calls
):
    async def fake_locate(**kwargs):
        locate_calls.append(kwargs)
        return {
            "element": {
                "rect": {"left": 1600, "top": 700, "width": 20, "height": 20},
                "center": [1641, 721],
            }
        }

    monkeypatch.setattr(element_describer, "locate_service", fake_locate)

    result = await verify_element_description_at_point(
        _agent(),
        "Mapped submit button",
        [50, 25],
        {
            "screenshot_base64": _SCREENSHOT,
            "coordinate_space": "logical",
            "logical_size": {"width": 100, "height": 50},
            "center_distance_threshold": 8,
        },
    )

    assert result["pass"] is True
    assert result["rect"] == {"left": 1600, "top": 700, "width": 20, "height": 20}
    assert result["center"] == [1641, 721]
    assert result["centerDistance"] == 0
    assert result["includedInRect"] is False


@pytest.mark.asyncio
async def test_rejects_empty_explicit_element_descriptions_before_verifying(
    monkeypatch, locate_calls
):
    async def failing_locate(**kwargs):
        raise AssertionError("should not verify locator")

    monkeypatch.setattr(element_describer, "locate_service", failing_locate)

    with pytest.raises(ValueError, match="description must not be empty"):
        await verify_element_description_at_point(_agent(), "   ", [10, 10])


@pytest.mark.skip(
    reason="Python verify_locator calls locate_service with a context object, "
    "not the upstream uiContext/xpath/cacheable LocateOption contract"
)
@pytest.mark.asyncio
async def test_uses_screenshot_context_without_scaling_screenshot_space_coordinates_and_honors_explicit_deep_locate_for_verification():
    pass


@pytest.mark.skip(
    reason="Python does not normalize a raw screenshot body to a PNG data URL "
    "in the frozen UIContext (ensure_data_url defaults raw bodies to jpeg)"
)
@pytest.mark.asyncio
async def test_normalizes_raw_screenshot_base64_into_a_data_url_context():
    pass


@pytest.mark.skip(
    reason="upstream case exercises Agent.aiLocate, which is outside the "
    "element-describer module covered by this file"
)
@pytest.mark.asyncio
async def test_passes_ui_context_override_into_ai_locate_execution():
    pass


@pytest.mark.skip(
    reason="Python ModelRuntime has no reasoningEnabled flags to assert after "
    "the first describeElementAtPoint failure"
)
@pytest.mark.asyncio
async def test_does_not_enable_locator_model_reasoning_after_the_first_describe_element_at_point_failure():
    pass
