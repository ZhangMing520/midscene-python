"""JSON parsing helpers for model responses.

Synced from upstream packages/core/src/ai-model/shared/json.ts
(extractJSONFromCodeBlock, parseModelResponseJson, assertJsonObject).
The upstream uses the `jsonrepair` package; we apply an equivalent repair
chain (code-fence stripping, trailing commas, smart quotes, python literals)
and optionally delegate to the `json_repair` package when installed.
"""

import json
import re
from typing import Any, Dict, Optional, Sequence


def extract_json_from_code_block(response: str) -> str:
    """Extract the JSON portion from a model response."""
    try:
        json_match = re.match(r"^\s*(\{[\s\S]*\})\s*$", response)
        if json_match:
            return json_match.group(1)

        code_block_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", response)
        if code_block_match:
            return code_block_match.group(1)

        json_like_match = re.search(r"\{[\s\S]*\}", response)
        if json_like_match:
            return json_like_match.group(0)
    except Exception:
        pass
    return response


def _repair_json_string(json_str: str) -> str:
    """Best-effort repairs for common LLM JSON issues (a light jsonrepair)."""
    repaired = json_str

    # Remove trailing commas before } or ]
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

    # Normalize smart quotes
    repaired = repaired.replace("\u201c", '"').replace("\u201d", '"')
    repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")

    # Replace Python-style literals
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bundefined\b", "null", repaired)

    # Quote unquoted keys: { key: "value" } -> { "key": "value" }
    repaired = re.sub(
        r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)",
        r'\1"\2"\3',
        repaired,
    )

    # Wrap bare newlines inside strings is out of scope; try brace balancing
    # for truncated output.
    open_braces = repaired.count("{") - repaired.count("}")
    if open_braces > 0:
        # Trim an incomplete trailing string, then close the braces.
        trimmed = re.sub(r",\s*\"[^\"]*$", "", repaired)
        repaired = trimmed
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")
        tail = ""
        if repaired.rstrip().endswith(","):
            repaired = repaired.rstrip()[:-1]
        open_brackets = repaired.count("[") - repaired.count("]")
        open_braces = repaired.count("{") - repaired.count("}")
        tail = "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        repaired = repaired + tail

    return repaired


def _parse_json_with_repair(json_str: str) -> Any:
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    try:  # optional dependency providing a robust repair implementation
        from json_repair import repair_json  # type: ignore

        return json.loads(repair_json(json_str))
    except Exception:
        pass

    return json.loads(_repair_json_string(json_str))


def assert_json_object(parsed: Any) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        if isinstance(parsed, list):
            parsed_type = "array"
        elif parsed is None:
            parsed_type = "null"
        else:
            parsed_type = type(parsed).__name__
        raise ValueError(
            "LLM response is valid JSON but does not match the expected schema. "
            f"Expected to be a JSON object, got {parsed_type}: {json.dumps(parsed, ensure_ascii=False)}."
        )
    return parsed


def _trim_parsed_json_strings(
    obj: Any, preserve_string_value_keys: Optional[Sequence[str]] = None
) -> Any:
    preserve = set(preserve_string_value_keys or [])

    def trim(value: Any, in_preserved_key: bool = False) -> Any:
        if value is None:
            return value
        if isinstance(value, list):
            return [trim(item) for item in value]
        if isinstance(value, dict):
            normalized: Dict[str, Any] = {}
            for key, val in value.items():
                trimmed_key = key.strip() if isinstance(key, str) else key
                keep_raw = trimmed_key in preserve
                normalized[trimmed_key] = trim(val, in_preserved_key=keep_raw)
            return normalized
        if isinstance(value, str):
            return value if in_preserved_key else value.strip()
        return value

    return trim(obj)


JsonParserSource = str  # 'generic-object' | 'planning-action-param' | 'locate' | 'section-locator'


def parse_model_response_json(
    raw: str,
    source: JsonParserSource = "generic-object",
    preserve_string_value_keys: Optional[Sequence[str]] = None,
) -> Any:
    """Parse a model response into JSON, with code-fence extraction and repair."""
    clean_json_string = extract_json_from_code_block(raw)

    try:
        parsed_obj = _parse_json_with_repair(clean_json_string)
    except Exception as e1:
        raise ValueError(
            f"failed to parse LLM response into JSON. Error - {e1}. Response - \n {raw}"
        ) from e1

    return _trim_parsed_json_strings(parsed_obj, preserve_string_value_keys)
