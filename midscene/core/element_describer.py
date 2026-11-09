"""Element describer (upstream packages/core/src/element-describer.ts).

Public helpers that answer "what is the element at this point?" and "is this
description really the element at this point?". Both work on the live UI or on
a screenshot supplied by the caller (`screenshotBase64`).
"""

import inspect
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .ai_model.adapters import ModelRuntime
from .ai_model.image_ops import image_size
from .ai_model.workflows.describe import ai_describe_element
from .ai_model.workflows.locate_service import locate_service
from .types import NodeType, Rect, Size, UIContext, UINode, UITree

DEFAULT_CENTER_DISTANCE_THRESHOLD = 20
DEFAULT_RETRY_LIMIT = 3

LocatorVerifyFn = Callable[[Dict[str, Any]], Union[Dict[str, Any], bool]]


def _distance(p1: Sequence[float], p2: Sequence[float]) -> int:
    return round(math.hypot(float(p1[0]) - float(p2[0]), float(p1[1]) - float(p2[1])))


def _included_in_rect(point: Sequence[float], rect: Dict[str, float]) -> bool:
    x, y = float(point[0]), float(point[1])
    left, top = float(rect["left"]), float(rect["top"])
    return (
        left <= x <= left + float(rect["width"])
        and top <= y <= top + float(rect["height"])
    )


def build_locate_validator_result(
    expect_center: Sequence[float],
    located: Dict[str, Any],
    center_distance_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Upstream LocateValidatorResult: pass when close enough or inside the rect."""
    center = list(located.get("center") or [])
    rect = located.get("rect")
    distance = _distance(expect_center, center) if len(center) >= 2 else None
    included = (
        _included_in_rect(expect_center, rect) if isinstance(rect, dict) else None
    )
    threshold = center_distance_threshold or DEFAULT_CENTER_DISTANCE_THRESHOLD
    passed = bool(included) or (distance is not None and distance <= threshold)
    return {
        "pass": passed,
        "rect": rect,
        "center": center,
        "centerDistance": distance,
        "includedInRect": included,
    }


def _bound_context(screenshot_base64: str, opt: Dict[str, Any]) -> UIContext:
    """A frozen UIContext over a caller-supplied screenshot (upstream helper)."""
    size = image_size(screenshot_base64)
    size = Size(width=float(size["width"]), height=float(size["height"]))
    return UIContext(
        screenshot_base64=screenshot_base64,
        size=size,
        content=[],
        tree=UITree(
            node=UINode(
                id="screenshot-root",
                content="",
                rect=Rect(left=0.0, top=0.0, width=size.width, height=size.height),
                center=(size.width / 2, size.height / 2),
                node_type=NodeType.CONTAINER,
            )
        ),
        shrunk_shot_to_logical_ratio=1.0,
    )


def _map_point_to_screenshot_space(
    center: Sequence[float],
    shot_size: Size,
    opt: Dict[str, Any],
) -> List[float]:
    if (opt.get("coordinate_space") or "screenshot") == "screenshot":
        return [float(center[0]), float(center[1])]
    logical = opt.get("logical_size")
    if not logical:
        raise ValueError("logical_size is required when coordinate_space is logical")
    width = logical["width"] if isinstance(logical, dict) else logical.width
    height = logical["height"] if isinstance(logical, dict) else logical.height
    return [
        float(center[0]) * shot_size.width / float(width),
        float(center[1]) * shot_size.height / float(height),
    ]


async def _resolve_target(
    agent: Any,
    center: Sequence[float],
    opt: Dict[str, Any],
) -> Dict[str, Any]:
    screenshot = opt.get("screenshot_base64")
    if not screenshot:
        return {"context": None, "center": [float(center[0]), float(center[1])]}
    context = _bound_context(screenshot, opt)
    mapped = _map_point_to_screenshot_space(center, context.size, opt)
    return {"context": context, "center": mapped}


def _describe_runtime(agent: Any) -> ModelRuntime:
    return agent._resolve_runtime("extract")


def _locate_runtime(agent: Any) -> ModelRuntime:
    return agent._resolve_runtime("locate")


async def _apply_locator_verify_fn(
    locator_verify_fn: Optional[LocatorVerifyFn],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if locator_verify_fn is None:
        return payload["verifyResult"]
    custom = locator_verify_fn(payload)
    if inspect.isawaitable(custom):
        custom = await custom
    if isinstance(custom, bool):
        return {**payload["verifyResult"], "pass": custom}
    return custom


async def verify_locator(
    agent: Any,
    prompt: str,
    expect_center: Sequence[float],
    opt: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Locate ``prompt`` again and check it still lands on ``expect_center``."""
    opt = opt or {}
    description = (prompt or "").strip()
    if not description:
        raise ValueError("description must not be empty")
    target = await _resolve_target(agent, expect_center, opt)
    context = target["context"] or opt.get("context")
    if context is None:
        context = await agent.get_context()
    response = await locate_service(
        query_prompt=description,
        context=context,
        model_runtime=_locate_runtime(agent),
        deep_locate=bool(opt.get("deep_locate", opt.get("deepLocate", False))),
    )
    element = response.get("element")
    if not element:
        errors = response.get("errors") or []
        details = "; ".join(errors)
        message = f"Element not found: {description}"
        raise ValueError(f"{message} ({details})" if details else message)
    return build_locate_validator_result(
        target["center"], element, opt.get("center_distance_threshold")
    )


async def verify_element_description_at_point(
    agent: Any,
    description: str,
    center: Sequence[float],
    opt: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Does ``description`` locate to the element at ``center``?"""
    return await verify_locator(agent, description, center, opt)


async def describe_element_at_point(
    agent: Any,
    center: Sequence[float],
    opt: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Describe the element at ``center`` and verify the description locates back.

    Retries up to ``retry_limit`` times; from the second attempt on,
    ``deep_describe`` / ``deep_locate`` switch on unless explicitly given.
    Returns {prompt, deepDescribe, deepLocate, verifyResult, success, error,
    failureStage}.
    """
    opt = opt or {}
    verify_prompt = opt.get("verify_prompt", opt.get("verifyPrompt", True))
    retry_limit = int(opt.get("retry_limit", opt.get("retryLimit", DEFAULT_RETRY_LIMIT)))
    auto_deep_describe = ("deep_describe" not in opt) and ("deepDescribe" not in opt)
    auto_deep_locate = ("deep_locate" not in opt) and ("deepLocate" not in opt)
    deep_describe = bool(opt.get("deep_describe", opt.get("deepDescribe", False)))
    deep_locate = bool(opt.get("deep_locate", opt.get("deepLocate", False)))
    on_progress = opt.get("on_progress", opt.get("onProgress"))
    locator_verify_fn = opt.get("locator_verify_fn", opt.get("locatorVerifyFn"))

    target = await _resolve_target(agent, center, opt)
    context = target["context"] or opt.get("context")
    if context is None:
        context = await agent.get_context()
    target_center = target["center"]
    describe_runtime = _describe_runtime(agent)

    success = False
    retry_count = 0
    result_prompt = ""
    verify_result: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    failure_stage: Optional[str] = None

    while not success and retry_count < retry_limit:
        if retry_count >= 1 and auto_deep_describe:
            deep_describe = True
        if retry_count >= 1 and auto_deep_locate:
            deep_locate = True
        try:
            described = await ai_describe_element(
                context, target_center, describe_runtime, deep_describe
            )
        except Exception as error:
            return {
                "prompt": result_prompt,
                "deepDescribe": deep_describe,
                "deepLocate": deep_locate,
                "verifyResult": verify_result,
                "success": False,
                "error": str(error),
                "failureStage": "describe",
            }
        result_prompt = described["description"]
        if not verify_prompt:
            if on_progress:
                on_progress({
                    "prompt": result_prompt,
                    "deepDescribe": deep_describe,
                    "deepLocate": deep_locate,
                })
            success = True
            break

        try:
            candidate = await verify_locator(
                agent,
                result_prompt,
                target_center,
                {
                    "center_distance_threshold": opt.get("center_distance_threshold"),
                    "deep_locate": deep_locate,
                    "context": context,
                    "coordinate_space": "screenshot",
                },
            )
            verify_result = await _apply_locator_verify_fn(
                locator_verify_fn,
                {
                    "prompt": result_prompt,
                    "expectCenter": target_center,
                    "retryCount": retry_count,
                    "verifyResult": candidate,
                },
            )
            if on_progress:
                on_progress({
                    "prompt": result_prompt,
                    "deepDescribe": deep_describe,
                    "deepLocate": deep_locate,
                    "verifyResult": verify_result,
                })
            if verify_result.get("pass"):
                success = True
                break
            last_error = None
            failure_stage = "verify"
        except Exception as error:
            last_error = str(error)
            failure_stage = "verify"
            if on_progress:
                on_progress({
                    "prompt": result_prompt,
                    "deepDescribe": deep_describe,
                    "deepLocate": deep_locate,
                })
        retry_count += 1

    return {
        "prompt": result_prompt,
        "deepDescribe": deep_describe,
        "deepLocate": deep_locate,
        "verifyResult": verify_result,
        "success": success,
        "error": (
            None
            if success or not verify_prompt
            else last_error or "describeElementAtPoint verify failed"
        ),
        "failureStage": None if success else failure_stage,
    }


__all__ = [
    "build_locate_validator_result",
    "describe_element_at_point",
    "verify_element_description_at_point",
    "verify_locator",
]