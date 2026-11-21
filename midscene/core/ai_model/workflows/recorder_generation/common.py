"""Recorder event helpers (upstream workflows/recorder-generation/common.ts)."""

from typing import Any, Dict, List, Optional
import hashlib
import json

def validate_events(events: List[Dict[str, Any]]) -> None:
    """Recorded events must be non-empty and well-formed (upstream validateEvents)."""
    if not events:
        raise ValueError("no recorded events to convert")
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"event #{index} is not an object")
        if not event.get("type"):
            raise ValueError(f"event #{index} is missing a type")


def create_event_counts(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"navigation": 0, "click": 0, "input": 0, "scroll": 0, "total": len(events)}
    for event in events:
        event_type = event.get("type", "")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _event_hash_id(event: Dict[str, Any], index: int) -> str:
    raw = json.dumps(event, sort_keys=True, ensure_ascii=False) + str(index)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def process_events_for_llm(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign hash ids and carry descriptions/values (upstream
    processEventsForLLM)."""
    processed: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        item = dict(event)
        item["hashId"] = _event_hash_id(event, index)
        semantic = event.get("semantic") or {}
        if semantic.get("status") == "ready":
            item["description"] = (
                semantic.get("elementDescription") or event.get("description") or ""
            )
            item["value"] = semantic.get("replayInstruction") or event.get("value") or ""
        processed.append(item)
    return processed


def prepare_event_summary(
    events: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the EventSummary payload embedded in the generation prompt."""
    options = options or {}
    processed = process_events_for_llm(events)
    urls: List[str] = []
    for event in processed:
        url = event.get("url")
        if url and url not in urls:
            urls.append(url)
    return {
        "testName": options.get("testName") or "recorder-test",
        "startUrl": urls[0] if urls else "",
        "eventCounts": create_event_counts(events),
        "urls": urls,
        "clickDescriptions": [
            e.get("description", "") for e in processed if e.get("type") == "click"
        ],
        "inputDescriptions": [
            {"description": e.get("description", ""), "value": e.get("value", "")}
            for e in processed
            if e.get("type") == "input"
        ],
        "events": processed,
    }


def stringify_target_block(target: Dict[str, Any]) -> str:
    """Serialize the target block for the prompt (upstream
    stringifyMidsceneRecorderTargetBlock)."""
    lines = [f"{target.get('platformId', 'web')}:"]
    for key, value in (target.get("values") or {}).items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def get_global_default_config() -> Dict[str, Any]:
    from midscene.shared.env import get_global_model_config_manager

    return get_global_model_config_manager().get_model_config("default")


def _recorder_stream_options(
    options: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Upstream streams only when both `stream` and `onChunk` are provided and
    silently falls back to a non-streaming call otherwise."""
    if options.get("stream") and options.get("onChunk"):
        return {"stream": True, "onChunk": options["onChunk"]}
    return None
