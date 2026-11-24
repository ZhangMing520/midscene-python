"""Parse MIDSCENE_* env into model config (upstream packages/shared/src/env/parse-model-config.ts)."""

import json
import math

from loguru import logger

from midscene.shared.env.constants import (
    DEFAULT_RETRY_INTERVAL_MS,
    KEYS_MAP,
    LEGACY_DEFAULT_KEYS,
    MIDSCENE_USE_DOUBAO_VISION,
    MIDSCENE_USE_GEMINI,
    MIDSCENE_USE_QWEN3_VL,
    MIDSCENE_USE_QWEN_VL,
    MIDSCENE_USE_VLM_UI_TARS,
    MODEL_CONFIG_DOC_URL,
    MODEL_FAMILY_VALUES,
)
from midscene.shared.env.types import (
    TIntent,
)


def model_family_required_for_locate_message(slot: str | None = None) -> str:
    """Deprecated re-export of the model-locate-result error message."""
    from midscene.core.ai_model.shared.model_locate_result.errors import (
        model_family_required_for_locate_message as _message,
    )

    return _message(slot)


def planning_model_family_required_for_locate_message(
    slot: str | None = None,
) -> str:
    """Deprecated re-export of the model-locate-result error message."""
    from midscene.core.ai_model.shared.model_locate_result.errors import (
        planning_model_family_required_for_locate_message as _message,
    )

    return _message(slot)


def legacy_config_to_model_family(provider: dict[str, str | None]) -> str | None:
    """Map deprecated MIDSCENE_USE_* vision switches to a model family."""
    is_doubao = provider.get(MIDSCENE_USE_DOUBAO_VISION)
    is_qwen = provider.get(MIDSCENE_USE_QWEN_VL)
    is_qwen3 = provider.get(MIDSCENE_USE_QWEN3_VL)
    is_ui_tars = provider.get(MIDSCENE_USE_VLM_UI_TARS)
    is_gemini = provider.get(MIDSCENE_USE_GEMINI)

    enabled_modes = [
        flag and key
        for flag, key in (
            (is_doubao, MIDSCENE_USE_DOUBAO_VISION),
            (is_qwen, MIDSCENE_USE_QWEN_VL),
            (is_qwen3, MIDSCENE_USE_QWEN3_VL),
            (is_ui_tars, MIDSCENE_USE_VLM_UI_TARS),
            (is_gemini, MIDSCENE_USE_GEMINI),
        )
        if flag
    ]
    if len(enabled_modes) > 1:
        raise ValueError(
            "Only one vision mode can be enabled at a time. Currently enabled modes: "
            f"{', '.join(enabled_modes)}. Please disable all but one mode."
        )

    if is_qwen3:
        return "qwen3-vl"
    if is_qwen:
        return "qwen2.5-vl"
    if is_doubao:
        return "doubao-vision"
    if is_gemini:
        return "gemini"
    if is_ui_tars:
        if is_ui_tars == "1":
            return "vlm-ui-tars"
        if is_ui_tars in ("DOUBAO", "DOUBAO-1.5"):
            return "vlm-ui-tars-doubao-1.5"
        return "vlm-ui-tars-doubao"
    return None


def get_uitars_model_version(model_family: str | None = None) -> str | None:
    if model_family == "vlm-ui-tars":
        return "1.0"
    if model_family in ("vlm-ui-tars-doubao", "vlm-ui-tars-doubao-1.5"):
        return "doubao-1.5-20B"
    return None


# Upstream export name is `getUITarsModelVersion`; this is its snake_case alias.
get_ui_tars_model_version = get_uitars_model_version


def validate_model_family(model_family: str | None) -> None:
    if model_family and model_family not in MODEL_FAMILY_VALUES:
        import midscene

        version = getattr(midscene, "__version__", "unknown")
        raise ValueError(
            f"Invalid MIDSCENE_MODEL_FAMILY value: {model_family}. Current version "
            f"v{version} accepts the following model families: "
            f"{', '.join(MODEL_FAMILY_VALUES)}. You can also visit "
            "https://www.midscenejs.com/model-api-setup.html for the latest "
            "configuration information."
        )


def get_model_description(
    model_family: str | None, ui_tars_model_version: str | None
) -> str:
    if ui_tars_model_version:
        return f"UI-TARS={ui_tars_model_version}"
    if model_family:
        return f"{model_family} mode"
    return ""


def _parse_temperature(raw: str | None) -> float | str | None:
    if raw == "unset":
        return "unset"
    if raw is None or raw == "":
        return None
    try:
        temperature = float(raw)
    except ValueError:
        return None
    return temperature if temperature == temperature else None  # NaN check


def _parse_number_env(
    raw: str | None,
    key: str,
    default: float | None,
    minimum: float | None = 0,
) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{key} must be a finite number, got {raw!r}") from None
    if value != value:  # NaN
        raise ValueError(f"{key} must be a finite number, got {raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}, got {value}")
    return value


def _parse_json_env(key: str, value: str | None) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse {key} as a JSON. {e}") from e
    if not isinstance(parsed, dict):
        return None
    return parsed


def _parse_timeout(raw: str | None, key: str) -> float | None:
    """Parse a timeout in milliseconds, mirroring upstream Number() checks."""
    if raw is None:
        return None
    if raw.strip() == "":
        raise ValueError(
            f"{key} must be a finite number greater than or equal to 0, "
            f"got {json.dumps(raw)}"
        )
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value < 0:
        raise ValueError(
            f"{key} must be a finite number greater than or equal to 0, "
            f"got {json.dumps(raw)}"
        )
    return value


def parse_openai_sdk_config(
    keys: dict[str, str],
    provider: dict[str, str | None],
    use_legacy_logic: bool = False,
) -> dict:
    """Parse a per-intent model configuration from an env-style key/value map.

    Ported from upstream parse-model-config.ts (parseOpenaiSdkConfig).
    """

    def pick(field: str) -> str | None:
        value = provider.get(keys[field])
        if value is None and use_legacy_logic and field in LEGACY_DEFAULT_KEYS:
            for legacy_key in LEGACY_DEFAULT_KEYS[field]:
                value = provider.get(legacy_key)
                if value is not None:
                    break
        return value

    model_family_raw = pick("modelFamily")
    if not model_family_raw and use_legacy_logic:
        model_family_raw = legacy_config_to_model_family(provider)

    model_family = model_family_raw or None
    validate_model_family(model_family)

    endpoint = pick("endpoint")
    if endpoint and model_family != "jev":
        raise ValueError(
            f"{keys['endpoint']} is only supported for System One models (currently Jev)"
        )

    ui_tars_model_version = get_uitars_model_version(model_family)

    auth_mode = (pick("authMode") or "api-key").strip() or "api-key"
    if auth_mode not in ("api-key", "siwc"):
        raise ValueError(
            f'Invalid {keys["authMode"]}: "{auth_mode}". Expected "api-key" or "siwc".'
        )

    protocol = pick("protocol")
    if protocol is not None and protocol not in ("openai-chat", "openai-responses"):
        raise ValueError(
            f"{keys['protocol']} must be one of: openai-chat, openai-responses. "
            f"Got: {protocol}"
        )

    stream_mode = (pick("streamMode") or "non-stream").strip() or "non-stream"
    if stream_mode not in ("stream", "non-stream"):
        raise ValueError(
            f'Invalid {keys["streamMode"]}: "{stream_mode}". '
            'Expected "stream" or "non-stream".'
        )

    timeout = _parse_timeout(pick("timeout"), keys["timeout"])

    retry_count_raw = pick("retryCount")
    retry_count = 1
    if retry_count_raw:
        try:
            retry_count = int(float(retry_count_raw))
        except ValueError:
            retry_count = 1
        if retry_count < 0:
            raise ValueError(
                f"{keys['retryCount']} must be non-negative, got {retry_count}"
            )

    retry_interval = _parse_number_env(
        pick("retryInterval"), keys["retryInterval"], DEFAULT_RETRY_INTERVAL_MS
    )

    reasoning_effort = (pick("reasoningEffort") or "").strip() or None

    reasoning_enabled_raw = (pick("reasoningEnabled") or "").strip().lower()
    reasoning_enabled: bool | str | None = None
    if reasoning_enabled_raw in ("true", "1"):
        reasoning_enabled = True
    elif reasoning_enabled_raw in ("false", "0"):
        reasoning_enabled = False
    elif reasoning_enabled_raw == "default":
        reasoning_enabled = "default"

    reasoning_budget_raw = (pick("reasoningBudget") or "").strip()
    reasoning_budget: int | None = None
    if reasoning_budget_raw:
        try:
            reasoning_budget = int(float(reasoning_budget_raw))
        except ValueError:
            reasoning_budget = None

    response_format = (pick("responseFormat") or "").strip().lower()
    if not response_format or response_format == "auto":
        response_format = "auto"
    elif response_format != "none":
        raise ValueError(
            f"{keys['responseFormat']} must be one of: none, auto. Got: {response_format}"
        )

    model_name = pick("modelName") or ""

    return {
        "socksProxy": pick("socksProxy"),
        "httpProxy": pick("httpProxy"),
        "authMode": auth_mode,
        "openaiBaseURL": pick("openaiBaseURL"),
        "endpoint": endpoint,
        "openaiApiKey": pick("openaiApiKey"),
        "openaiExtraConfig": _parse_json_env(
            keys["openaiExtraConfig"], pick("openaiExtraConfig")
        ),
        "extraBody": _parse_json_env(keys["extraBody"], pick("extraBody")),
        "protocol": protocol,
        "modelFamily": model_family,
        "uiTarsModelVersion": ui_tars_model_version,
        "modelName": model_name,
        "modelDescription": get_model_description(model_family, ui_tars_model_version),
        "timeout": timeout,
        "temperature": _parse_temperature(pick("temperature")),
        "streamMode": stream_mode,
        "retryCount": retry_count,
        "retryInterval": retry_interval,
        "reasoningEffort": reasoning_effort,
        "reasoningEnabled": reasoning_enabled,
        "reasoningBudget": reasoning_budget,
        "responseFormat": response_format,
    }


def decide_model_config_from_intent_config(
    intent: TIntent, config_map: dict[str, str | None]
) -> dict | None:
    """Resolve one intent's model config; returns None when no model name is set."""
    keys_for_intent = KEYS_MAP[intent]
    model_name = config_map.get(keys_for_intent["modelName"])
    if not model_name:
        return None

    result = parse_openai_sdk_config(
        keys=keys_for_intent,
        provider=config_map,
        use_legacy_logic=(intent == "default"),
    )
    result["intent"] = intent
    result["slot"] = intent

    if result["authMode"] != "siwc" and not (
        result["endpoint"] or result["openaiBaseURL"]
    ):
        raise ValueError(
            f"failed to get base URL or System One endpoint of model (intent={intent}). "
            f"See {MODEL_CONFIG_DOC_URL}"
        )

    if not result["modelName"]:
        logger.warning(
            f"modelName is not set for intent {intent}, this may cause unexpected "
            f"behavior. See {MODEL_CONFIG_DOC_URL}"
        )
    return result
