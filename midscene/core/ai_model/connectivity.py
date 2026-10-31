"""Model connectivity test.

Synced from upstream packages/core/src/ai-model/connectivity/run-connectivity-test.ts.
Runs four checks in parallel: planning text, insight vision, aiLocate
(grounding pipeline), default text.
"""

import base64
import io
import time
from typing import Any, Callable, Dict, List

from loguru import logger

from .adapters import ModelRuntime, get_model_runtime
from .caller import call_generative_ai
from .system_one import call_system_one

TEXT_EXPECTED_TOKEN = "CONNECTIVITY_OK"


def _fixture_png_data_url(width: int = 320, height: int = 100) -> str:
    """A synthetic form-like fixture image (upstream embeds a form screenshot)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle([16, 20, 200, 44], outline=(120, 120, 120), width=2)
    draw.rectangle([16, 60, 280, 84], outline=(120, 120, 120), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


CONNECTIVITY_FIXTURE_IMAGE = None
CONNECTIVITY_FIXTURE_SHOT_SIZE = {"width": 320, "height": 100}


async def _text_check(model_runtime: ModelRuntime) -> Dict[str, Any]:
    response = await call_generative_ai(
        [
            {
                "role": "system",
                "content": "Reply with the exact token the user asks for.",
            },
            {"role": "user", "content": f"Return exactly {TEXT_EXPECTED_TOKEN}"},
        ],
        model_runtime,
    )
    return {"passed": TEXT_EXPECTED_TOKEN in response["content"], "content": response["content"]}


async def _jev_text_check(model_runtime: ModelRuntime) -> Dict[str, Any]:
    response = await call_system_one(
        model_runtime,
        {
            "state": {"token": TEXT_EXPECTED_TOKEN},
            "questions": {
                "result": {
                    "type": "noul",
                    "instructions": "Does token equal CONNECTIVITY_OK?",
                }
            },
        },
    )
    answer = response["answers"]["result"]
    return {"passed": answer["type"] == "noul" and answer["noul"] >= 0.5, "content": response["content"]}


async def _vision_check(model_runtime: ModelRuntime) -> Dict[str, Any]:
    global CONNECTIVITY_FIXTURE_IMAGE
    if CONNECTIVITY_FIXTURE_IMAGE is None:
        CONNECTIVITY_FIXTURE_IMAGE = _fixture_png_data_url()
    if model_runtime.config.get("modelFamily") == "jev":
        response = await call_system_one(
            model_runtime,
            {
                "state": {},
                "images": {"screenshot": CONNECTIVITY_FIXTURE_IMAGE},
                "questions": {
                    "result": {
                        "type": "noul",
                        "instructions": "Does `screenshot` show a form?",
                    }
                },
            },
        )
        answer = response["answers"]["result"]
        return {"passed": answer["type"] == "noul" and answer["noul"] >= 0.5}
    response = await call_generative_ai(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "What is the main content of this image ? It is a photo or a form ?",
                    },
                    {"type": "image", "url": CONNECTIVITY_FIXTURE_IMAGE},
                ],
            }
        ],
        model_runtime,
    )
    return {"passed": True, "content": response["content"]}


async def _ai_locate_check(model_runtime: ModelRuntime) -> Dict[str, Any]:
    global CONNECTIVITY_FIXTURE_IMAGE
    if CONNECTIVITY_FIXTURE_IMAGE is None:
        CONNECTIVITY_FIXTURE_IMAGE = _fixture_png_data_url()
    from .workflows.locate_service import locate_service

    class _FixtureContext:
        screenshot_base64 = CONNECTIVITY_FIXTURE_IMAGE
        size = type(
            "Size",
            (),
            CONNECTIVITY_FIXTURE_SHOT_SIZE,
        )()

    response = await locate_service(
        query_prompt="the main todo input box",
        context=_FixtureContext(),
        model_runtime=model_runtime,
    )
    element = response.get("element")
    center = element.get("center") if element else None
    has_valid_center = (
        isinstance(center, (list, tuple))
        and len(center) == 2
        and all(isinstance(v, (int, float)) for v in center)
    )
    return {"passed": has_valid_center, "content": response.get("raw_response") or ""}


async def _run_check(
    name: str,
    intent: str,
    model_config: Dict[str, Any],
    check_fn: Callable,
) -> Dict[str, Any]:
    config = {**model_config, "retryCount": 0, "intent": intent, "slot": intent}
    runtime = get_model_runtime(config)
    start = time.time()
    try:
        result = await check_fn(runtime)
        duration = int((time.time() - start) * 1000)
        message = "" if result["passed"] else f"Unexpected response: {result.get('content', '')[:200]}"
        return {
            "name": name,
            "intent": intent,
            "modelName": config.get("modelName"),
            "modelFamily": config.get("modelFamily"),
            "passed": result["passed"],
            "durationMs": duration,
            "message": message,
        }
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return {
            "name": name,
            "intent": intent,
            "modelName": config.get("modelName"),
            "modelFamily": config.get("modelFamily"),
            "passed": False,
            "durationMs": duration,
            "message": str(e),
        }


async def run_connectivity_test(config: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Run the four connectivity checks.

    config keys: defaultModelConfig (required), locateModelConfig?,
    planningModelConfig (required), insightModelConfig (required).
    """
    import asyncio

    checks = await asyncio.gather(
        _run_check(
            "text",
            "planning",
            config["planningModelConfig"],
            _jev_text_check
            if config["planningModelConfig"].get("modelFamily") == "jev"
            else _text_check,
        ),
        _run_check(
            "vision",
            "insight",
            config["insightModelConfig"],
            _vision_check,
        ),
        _run_check(
            "aiLocate",
            "locate",
            config.get("locateModelConfig") or config["defaultModelConfig"],
            _ai_locate_check,
        ),
        _run_check(
            "text",
            "default",
            config["defaultModelConfig"],
            _jev_text_check
            if config["defaultModelConfig"].get("modelFamily") == "jev"
            else _text_check,
        ),
    )

    check_list: List[Dict[str, Any]] = list(checks)
    passed = all(check["passed"] for check in check_list)
    result: Dict[str, Any] = {
        "checks": check_list,
        "requestCount": len(check_list),
        "passed": passed,
    }
    if not passed:
        result["message"] = "\n".join(
            f"[{check['name'].capitalize()} check - {check['modelName']} "
            f"({check['intent']})]: {check['message']}"
            for check in check_list
            if not check["passed"]
        )
    return result


__all__ = ["run_connectivity_test", "TEXT_EXPECTED_TOKEN", "logger"]
