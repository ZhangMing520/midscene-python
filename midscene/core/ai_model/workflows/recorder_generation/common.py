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


MAX_RECORDER_GENERATION_SEMANTIC_TEXT_LENGTH = 1200
MAX_RECORDER_GENERATION_SEMANTIC_ERROR_LENGTH = 400

_AI_ANALYZING_PLACEHOLDER = "AI is analyzing element..."


def _clean_recorder_semantic_field(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and value.strip() == _AI_ANALYZING_PLACEHOLDER:
        return None
    return value


def _truncate_recorder_generation_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}... [truncated {len(value) - max_length} chars]"


def _compact_semantic_text(value: Optional[str]) -> Optional[str]:
    cleaned = _clean_recorder_semantic_field(value)
    return (
        _truncate_recorder_generation_text(
            cleaned, MAX_RECORDER_GENERATION_SEMANTIC_TEXT_LENGTH
        )
        if cleaned
        else None
    )


def _compact_semantic_error(value: Optional[str]) -> Optional[str]:
    return (
        _truncate_recorder_generation_text(
            value, MAX_RECORDER_GENERATION_SEMANTIC_ERROR_LENGTH
        )
        if value
        else None
    )


def compact_recorder_semantic_for_generation(
    semantic: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Compact semantic text and drop fallback audit chains.

    Mirrors upstream ``compactRecorderSemanticForGeneration`` so metadata prompts
    never include long error chains or stale fallback sources.
    """
    if not semantic:
        return None

    compacted: Dict[str, Any] = {
        "source": semantic.get("source"),
        "status": semantic.get("status"),
        "confidence": semantic.get("confidence"),
        "elementDescription": _compact_semantic_text(
            semantic.get("elementDescription")
        ),
        "replayInstruction": _compact_semantic_text(
            semantic.get("replayInstruction")
        ),
        "actionSummary": _compact_semantic_text(semantic.get("actionSummary")),
        "error": _compact_semantic_error(semantic.get("error")),
    }
    ai_describe = semantic.get("aiDescribe")
    if ai_describe:
        compacted["aiDescribe"] = {
            "verifyPrompt": ai_describe.get("verifyPrompt"),
            "verifyPassed": ai_describe.get("verifyPassed"),
            "deepLocate": ai_describe.get("deepLocate"),
            "centerDistance": ai_describe.get("centerDistance"),
            "expectedCenter": ai_describe.get("expectedCenter"),
            "actualCenter": ai_describe.get("actualCenter"),
        }
    return compacted


def _recorder_stream_options(
    options: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Upstream streams only when both `stream` and `onChunk` are provided and
    silently falls back to a non-streaming call otherwise."""
    if options.get("stream") and options.get("onChunk"):
        return {"stream": True, "onChunk": options["onChunk"]}
    return None
