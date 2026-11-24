"""Recorder session metadata generation (upstream recorder-generation/metadata.ts)."""

import json
from typing import Any, cast

from midscene.core.ai_model.service_caller.model_call import (
    call_ai_with_object_response,
)
from midscene.core.ai_model.workflows.recorder_generation.common import (
    compact_recorder_semantic_for_generation,
)

SESSION_METADATA_PROMPT = """Generate a concise title (5-7 words) and brief description (1-2 sentences) for a Studio recording of user actions.

The recording can target Web, Android, iOS, HarmonyOS, or Computer. Do not assume it is a browser session unless the platform is web.
Describe what the user did or accomplished. The description should use the user as the subject, preferably starting with "The user ...". Do not start the description with "The session ...".
The title should be action-oriented and highlight the main task accomplished.

Summary:
{summary}

Respond with a JSON object containing exactly "title" and "description"."""


def _event_screenshot(event: dict[str, Any]) -> str | None:
    for key in ("screenshot", "imageBase64", "screenshotBase64"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    screenshots = event.get("screenshots")
    if isinstance(screenshots, list):
        for value in screenshots:
            if isinstance(value, str) and value:
                return value
    return None


def get_screenshots_for_llm(events: list[dict[str, Any]], limit: int = 1) -> list[str]:
    if limit <= 0:
        return []
    shots: list[str] = []
    for event in events:
        shot = _event_screenshot(event)
        if shot:
            shots.append(shot)
            if len(shots) >= limit:
                break
    return shots


def summarize_recorder_events(
    target: dict[str, Any],
    events: list[dict[str, Any]],
    fallback_name: str | None = None,
) -> dict[str, Any]:
    navigation = [event for event in events if event.get("type") == "navigation"]
    clicks = [event for event in events if event.get("type") == "click"]
    inputs = [event for event in events if event.get("type") == "input"]
    scrolls = [event for event in events if event.get("type") == "scroll"]
    urls = [event["url"] for event in navigation if event.get("url")]
    titles = [event["title"] for event in navigation if event.get("title")]
    return {
        "platform": target.get("platformId"),
        "target": target,
        "fallbackName": fallback_name,
        "pageCount": len(navigation),
        "pageTitles": titles[:5],
        "urls": urls[:5],
        "clickCount": len(clicks),
        "inputCount": len(inputs),
        "scrollCount": len(scrolls),
        "totalActions": len(events),
        "firstUrl": urls[0] if urls else (target.get("values") or {}).get("url", ""),
        "lastUrl": urls[-1] if urls else "",
        "events": [
            {
                key: value
                for key, value in {
                    "type": event.get("type"),
                    "actionType": event.get("actionType"),
                    "url": event.get("url"),
                    "title": event.get("title"),
                    "value": event.get("value"),
                    "description": _event_description(event),
                    "semantic": compact_recorder_semantic_for_generation(
                        event.get("semantic")
                    ),
                }.items()
                if value is not None
            }
            for event in events[:20]
        ],
    }


def _event_description(event: dict[str, Any]) -> str:
    semantic = event.get("semantic") or {}
    if semantic.get("status") == "ready" and semantic.get("elementDescription"):
        return cast(str, semantic["elementDescription"])
    return cast(str, event.get("description") or "")


def normalize_metadata_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


async def generate_recorder_session_metadata(
    target: dict[str, Any],
    events: list[dict[str, Any]],
    model_runtime: Any,
    fallback_name: str | None = None,
    max_screenshots: int = 1,
) -> dict[str, str]:
    """Generate a title/description pair for a recorded session."""
    if not events:
        raise ValueError("generate_recorder_session_metadata: events are required.")
    if not model_runtime.config.get("modelName"):
        raise ValueError(
            "generate_recorder_session_metadata: modelConfig.modelName is required."
        )

    summary = summarize_recorder_events(target, events, fallback_name)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": SESSION_METADATA_PROMPT.format(
                summary=json.dumps(summary, indent=2, ensure_ascii=False, default=str)
            ),
        }
    ]
    for shot in get_screenshots_for_llm(events, max_screenshots):
        content.append({"type": "image", "url": shot})

    response = await call_ai_with_object_response(
        [
            {
                "role": "system",
                "content": (
                    "You generate clear, task-oriented titles and descriptions "
                    "for recorded automation sessions."
                ),
            },
            {"role": "user", "content": content},
        ],
        model_runtime,
    )
    parsed = response["content"]
    return {
        "title": normalize_metadata_value(parsed.get("title")),
        "description": normalize_metadata_value(parsed.get("description")),
    }


__all__ = [
    "generate_recorder_session_metadata",
    "get_screenshots_for_llm",
    "normalize_metadata_value",
    "summarize_recorder_events",
]
