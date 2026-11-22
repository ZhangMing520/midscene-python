"""Agent helpers (upstream agent/utils.ts)."""

import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.types import (
    AbortError,
    AbortSignal,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)
from midscene.shared.env.constants import MIDSCENE_REPORT_QUIET
from midscene.shared.env.global_config_manager import get_global_config_manager
from midscene.shared.img import image_info_of_base64
from midscene.shared.img.transform import normalize_screenshot_base64
from midscene.shared.logger import log_report

_SCREENSHOT_DATA_URL_PATTERN = re.compile(
    r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE
)

_LEGACY_SCROLL_TYPE_MAP = {
    "once": "singleAction",
    "untilBottom": "scrollToBottom",
    "untilTop": "scrollToTop",
    "untilRight": "scrollToRight",
    "untilLeft": "scrollToLeft",
}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _strip_runtime_locate_result(value: Any) -> Any:
    """Drop screenshot-space coordinates before persisting/replaying a plan.

    Upstream `dumpActionParam` keeps only the locate prompt in cached flows;
    reusing `locatedPixelResult` from an older screenshot clicks stale
    coordinates.
    """
    if isinstance(value, dict):
        return {
            key: _strip_runtime_locate_result(item)
            for key, item in value.items()
            if key != "locatedPixelResult"
        }
    if isinstance(value, list):
        return [_strip_runtime_locate_result(item) for item in value]
    return value


def _get_opt(opt: Dict[str, Any], keys: tuple, default: Any = None) -> Any:
    for key in keys:
        if opt.get(key) is not None:
            return opt[key]
    return default


def _is_aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if isinstance(signal, AbortSignal):
        return signal.aborted
    aborted = getattr(signal, "aborted", None)
    if aborted is not None:
        return bool(aborted)
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    raise TypeError(
        "abortSignal must be an AbortSignal, asyncio.Event or threading.Event"
    )


def _throw_if_aborted(signal: Any) -> None:
    if not _is_aborted(signal):
        return
    thrower = getattr(signal, "throw_if_aborted", None)
    if callable(thrower):
        thrower()
        return
    reason = getattr(signal, "reason", None) or "signal already aborted"
    raise AbortError(
        f"Operation interrupted by an external abort signal.\nReason: {reason}"
    )


def _env_number(key: str) -> Optional[int]:
    raw = os.environ.get(key)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _extract_typed_query_result(data: Any, key: str) -> Any:
    """Extract a typed query value like upstream createTypeQueryTask.

    Plain strings pass through; dicts prefer the typed key, then `result`;
    anything else is returned as-is. Explicit null is preserved.
    """
    if isinstance(data, str):
        return data
    if data is None:
        return None
    if isinstance(data, dict):
        if key in data:
            return data[key]
        if "result" in data:
            return data["result"]
        raise ValueError("No result in query data")
    return data


async def _maybe_await(value: Any) -> Any:
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


def _js_round(value: float) -> int:
    """``Math.round`` semantics (half away from +infinity)."""
    return int(math.floor(float(value) + 0.5))


def _empty_tree(width: float, height: float) -> UITree:
    return UITree(
        node=UINode(
            id="screenshot-root",
            content="",
            rect=Rect(left=0.0, top=0.0, width=width, height=height),
            center=(width / 2, height / 2),
            node_type=NodeType.CONTAINER,
        )
    )


def _prompt_text(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        value = prompt.get("prompt")
        return value if isinstance(value, str) else ""
    return ""


def normalize_scroll_type(scroll_type: Optional[str]) -> Optional[str]:
    """Map the legacy scroll-type aliases to the current names."""
    if not scroll_type:
        return None
    return _LEGACY_SCROLL_TYPE_MAP.get(scroll_type, scroll_type)


def _normalize_screenshot_input(screenshot_base64: str) -> str:
    trimmed = (screenshot_base64 or "").strip()
    if _SCREENSHOT_DATA_URL_PATTERN.match(trimmed):
        return trimmed
    return normalize_screenshot_base64(trimmed)


def _validate_interface_size(width: float, height: float) -> None:
    if not math.isfinite(width) or not math.isfinite(height):
        raise ValueError(
            "Invalid interface size: width and height must be finite numbers. "
            f"Received width: {width}, height: {height}"
        )
    if width <= 0 or height <= 0:
        raise ValueError(
            "Invalid interface size: width and height must be positive numbers. "
            f"Received width: {width}, height: {height}"
        )


async def common_context_parser(
    interface_instance: Any,
    _opt: Optional[Dict[str, Any]] = None,
) -> UIContext:
    """Capture a UIContext from an interface (upstream commonContextParser)."""
    from midscene.core.agent.screenshot_preparation import (
        prepare_raw_screenshot,
    )

    _opt = _opt or {}
    if interface_instance is None:
        raise ValueError("interfaceInstance is required")

    describe = getattr(interface_instance, "describe", None)
    description = await _maybe_await(describe()) if callable(describe) else ""
    logger.debug(f"Getting interface description: {description or ''}")

    interface_size = await _maybe_await(interface_instance.size())
    if isinstance(interface_size, dict):
        logical_width = float(interface_size.get("width", 0))
        logical_height = float(interface_size.get("height", 0))
        dpr_hint = interface_size.get("dpr")
    else:
        logical_width = float(getattr(interface_size, "width", 0))
        logical_height = float(getattr(interface_size, "height", 0))
        dpr_hint = getattr(interface_size, "dpr", None)
    if dpr_hint is not None:
        logger.warning(
            "Warning: return value of interface.size() include a dpr property, "
            "which is not expected and ignored."
        )
    _validate_interface_size(logical_width, logical_height)

    screenshot_base64 = await _maybe_await(interface_instance.screenshot_base64())
    if not screenshot_base64:
        raise ValueError("screenshotBase64 is required")
    user_shrink_factor = _opt.get(
        "screenshotShrinkFactor", _opt.get("screenshot_shrink_factor", 1)
    )
    if user_shrink_factor is None:
        user_shrink_factor = 1

    prepared = await prepare_raw_screenshot(
        screenshot_base64, {"shrinkFactor": user_shrink_factor}
    )
    img_width = float(prepared["originalSize"]["width"])
    img_height = float(prepared["originalSize"]["height"])

    logical_is_portrait = logical_width < logical_height
    screenshot_is_portrait = img_width < img_height
    final_logical_width = logical_width
    final_logical_height = logical_height
    if logical_is_portrait != screenshot_is_portrait:
        logger.debug(
            "Orientation mismatch detected: logical size "
            f"{logical_width}x{logical_height} vs screenshot "
            f"{img_width}x{img_height}. Swapping logical dimensions."
        )
        final_logical_width = logical_height
        final_logical_height = logical_width

    dpr = img_width / final_logical_width
    shrunk_shot_to_logical_ratio = dpr / float(user_shrink_factor)
    logger.debug(
        "calculated dpr: "
        f"{dpr}, shrunkShotToLogicalRatio: {shrunk_shot_to_logical_ratio}"
    )

    return UIContext(
        screenshot_base64=prepared["base64"],
        size=Size(width=final_logical_width, height=final_logical_height),
        content=[],
        tree=_empty_tree(img_width, img_height),
        shrunk_shot_to_logical_ratio=shrunk_shot_to_logical_ratio,
    )


async def create_screenshot_bound_ui_context(
    screenshot_base64: str,
    opt: Optional[Dict[str, Any]] = None,
) -> UIContext:
    """Build a frozen UIContext over a caller-supplied screenshot."""
    opt = opt or {}
    normalized = _normalize_screenshot_input(screenshot_base64)
    actual_size = image_info_of_base64(normalized)
    provided = opt.get("screenshotSize", opt.get("screenshot_size"))
    if provided:
        provided_width = (
            provided.get("width") if isinstance(provided, dict) else provided.width
        )
        provided_height = (
            provided.get("height") if isinstance(provided, dict) else provided.height
        )
        if (
            provided_width != actual_size["width"]
            or provided_height != actual_size["height"]
        ):
            logger.debug(
                "describeElementAtPoint screenshotSize mismatch, use actual size",
                provided,
                actual_size,
            )

    return UIContext(
        screenshot_base64=normalized,
        size=Size(
            width=float(actual_size["width"]), height=float(actual_size["height"])
        ),
        content=[],
        tree=_empty_tree(actual_size["width"], actual_size["height"]),
        shrunk_shot_to_logical_ratio=1.0,
    )


def print_report_msg(filepath: str) -> None:
    """Print the report-updated message unless report output is quiet."""
    if get_global_config_manager().get_env_config_in_boolean(
        MIDSCENE_REPORT_QUIET
    ):
        return
    log_report(f"Midscene - report file updated: {filepath}")


def normalize_file_paths(
    files: Any,
    options: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Resolve file chooser paths and fail early when a file is missing."""
    options = options or {}
    file_exists = options.get("fileExists", options.get("file_exists"))
    is_in_browser = options.get(
        "isInBrowser", options.get("is_in_browser", False)
    )
    resolve_path = options.get("resolvePath", options.get("resolve_path"))
    wsl_distro_name = options.get(
        "wslDistroName",
        options.get("wsl_distro_name", os.environ.get("WSL_DISTRO_NAME")),
    )
    cwd = options.get("cwd") or os.getcwd()

    if is_in_browser:
        raise RuntimeError("File chooser is not supported in browser environment")

    items = files if isinstance(files, (list, tuple)) else [files]
    normalized: List[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError("File path must be a non-empty string")
        if resolve_path is not None:
            absolute_path = resolve_path(item)
        else:
            absolute_path = str(Path(item).expanduser().resolve())
        exists = file_exists(absolute_path) if file_exists else Path(
            absolute_path
        ).exists()
        if not exists:
            raise FileNotFoundError(
                f"File not found: {item}. Resolved to: {absolute_path}. "
                f"Current working directory: {cwd}"
            )

        if not wsl_distro_name:
            normalized.append(absolute_path)
            continue

        wsl_mount = re.match(r"^/mnt/([a-z])/", absolute_path)
        if wsl_mount:
            drive = wsl_mount.group(1).upper()
            tail = absolute_path[7:].replace("/", "\\")
            normalized.append(f"{drive}:\\{tail}")
        else:
            normalized.append(
                f"\\\\wsl$\\{wsl_distro_name}"
                + absolute_path.replace("/", "\\")
            )
    return normalized


def if_locate_param_has_located_pixel_result(plan_locate_param: Any) -> bool:
    """Whether a locate param carries a valid ``locatedPixelResult.center``."""
    if not isinstance(plan_locate_param, dict):
        return False
    result = plan_locate_param.get("locatedPixelResult")
    if not isinstance(result, dict) or "center" not in result:
        return False
    center = result.get("center")
    return (
        isinstance(center, (list, tuple))
        and len(center) == 2
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in center
        )
    )


def match_element_from_plan(plan_locate_param: Any) -> Optional[Dict[str, Any]]:
    """Convert plan coordinates into a locate result element."""
    if not plan_locate_param:
        return None
    located = plan_locate_param.get("locatedPixelResult")
    if not isinstance(located, dict):
        return None
    center = located.get("center")
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        return None
    element: Dict[str, Any] = {
        "center": list(center),
        "description": _prompt_text(plan_locate_param.get("prompt")),
    }
    rect = located.get("rect")
    if rect:
        element["rect"] = rect
    return element


def _rect_to_dict(rect: Any) -> Optional[Dict[str, float]]:
    if rect is None:
        return None
    if isinstance(rect, dict):
        return rect
    return {
        "left": rect.left,
        "top": rect.top,
        "width": rect.width,
        "height": rect.height,
    }


async def match_element_from_cache(
    context: Any,
    cache_entry: Any,
    cache_prompt: Any,
) -> Optional[Dict[str, Any]]:
    """Resolve a cached element feature into a locate result element."""
    if not cache_entry:
        return None

    if isinstance(context, dict):
        task_cache = context.get("taskCache", context.get("task_cache"))
        interface_instance = context.get(
            "interfaceInstance", context.get("interface_instance")
        )
    else:
        task_cache = getattr(context, "task_cache", None)
        interface_instance = getattr(context, "interface_instance", None)

    if not task_cache or not getattr(task_cache, "is_cache_result_used", False):
        return None
    resolver = getattr(
        interface_instance, "rect_matches_cache_feature", None
    )
    if not callable(resolver):
        logger.debug(
            "interface does not implement rectMatchesCacheFeature, skip cache"
        )
        return None

    try:
        rect = await _maybe_await(resolver(cache_entry))
        if rect is None:
            return None
        rect_dict = _rect_to_dict(rect)
        element: Dict[str, Any] = {
            "center": [
                rect_dict["left"] + rect_dict["width"] / 2,
                rect_dict["top"] + rect_dict["height"] / 2,
            ],
            "rect": rect_dict,
            "description": _prompt_text(cache_prompt),
        }
        logger.debug(f"cache hit, prompt: {cache_prompt}")
        return element
    except Exception as error:  # noqa: BLE001 - cache misses never fail locate
        logger.debug(f"rectMatchesCacheFeature error: {error}")
        return None


def get_midscene_version() -> str:
    """Return the built package version."""
    try:
        import midscene

        version = getattr(midscene, "__version__", None)
    except Exception:  # noqa: BLE001 - import failures surface below
        version = None
    if not version or version == "undefined":
        raise RuntimeError("__VERSION__ inject failed during build")
    return version


def parse_prompt(prompt: Any) -> Dict[str, Any]:
    """Split a user prompt into text and optional multimodal parts."""
    if isinstance(prompt, str):
        return {"textPrompt": prompt, "multimodalPrompt": None}
    if isinstance(prompt, dict):
        images = prompt.get("images")
        return {
            "textPrompt": prompt.get("prompt"),
            "multimodalPrompt": (
                {
                    "images": images,
                    "convertHttpImage2Base64": bool(
                        prompt.get("convertHttpImage2Base64")
                    ),
                }
                if images
                else None
            ),
        }
    return {"textPrompt": "" if prompt is None else str(prompt), "multimodalPrompt": None}


def transform_logical_rect_to_screenshot_rect(
    rect: Any,
    shrunk_shot_to_logical_ratio: float,
) -> Any:
    """Scale a logical-space rect into screenshot space."""
    if shrunk_shot_to_logical_ratio == 1:
        return rect
    if isinstance(rect, dict):
        return {
            **rect,
            "left": _js_round(rect["left"] * shrunk_shot_to_logical_ratio),
            "top": _js_round(rect["top"] * shrunk_shot_to_logical_ratio),
            "width": _js_round(rect["width"] * shrunk_shot_to_logical_ratio),
            "height": _js_round(rect["height"] * shrunk_shot_to_logical_ratio),
        }
    return Rect(
        left=_js_round(rect.left * shrunk_shot_to_logical_ratio),
        top=_js_round(rect.top * shrunk_shot_to_logical_ratio),
        width=_js_round(rect.width * shrunk_shot_to_logical_ratio),
        height=_js_round(rect.height * shrunk_shot_to_logical_ratio),
    )


def transform_logical_element_to_screenshot(
    element: Dict[str, Any],
    shrunk_shot_to_logical_ratio: float,
) -> Dict[str, Any]:
    """Scale a logical-space element into screenshot space."""
    if shrunk_shot_to_logical_ratio == 1:
        return element
    center = element.get("center")
    transformed: Dict[str, Any] = {
        **element,
        "center": (
            [
                center[0] * shrunk_shot_to_logical_ratio,
                center[1] * shrunk_shot_to_logical_ratio,
            ]
            if center is not None
            else center
        ),
    }
    if element.get("rect"):
        transformed["rect"] = transform_logical_rect_to_screenshot_rect(
            element["rect"], shrunk_shot_to_logical_ratio
        )
    return transformed


__all__ = [
    "common_context_parser",
    "create_screenshot_bound_ui_context",
    "get_midscene_version",
    "if_locate_param_has_located_pixel_result",
    "match_element_from_cache",
    "match_element_from_plan",
    "normalize_file_paths",
    "normalize_scroll_type",
    "parse_prompt",
    "print_report_msg",
    "transform_logical_element_to_screenshot",
    "transform_logical_rect_to_screenshot_rect",
]
