"""
Model environment configuration.

Synced from upstream web-infra-dev/midscene v1.17.4:
  packages/shared/src/env/types.ts       (env key constants, TModelFamily)
  packages/shared/src/env/constants.ts   (per-intent model config key maps)
  packages/shared/src/env/parse-model-config.ts
  packages/shared/src/env/model-config-manager.ts
  packages/shared/src/env/utils.ts       (getPreferredLanguage)
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from loguru import logger

try:  # Python >= 3.9
    import zoneinfo  # noqa: F401

    _HAS_ZONEINFO = True
except ImportError:  # pragma: no cover
    _HAS_ZONEINFO = False

MODEL_CONFIG_DOC_URL = "https://midscenejs.com/model-api-setup.html"

# ---------------------------------------------------------------------------
# Model family values (TModelFamily)
# ---------------------------------------------------------------------------

MODEL_FAMILY_VALUES: List[str] = [
    "jev",
    "ant-ling",
    "doubao-vision",
    "doubao-seed",
    "gemini",
    "qwen2.5-vl",
    "qwen3-vl",
    "qwen3",
    "qwen3.5",
    "qwen3.6",
    "vlm-ui-tars",
    "vlm-ui-tars-doubao",
    "vlm-ui-tars-doubao-1.5",
    "glm-v",
    "auto-glm",
    "auto-glm-multilingual",
    "gpt-5",
    "gpt-6",
    "deepseek",
    "kimi",
    "kimi3",
    "xiaomi-mimo",
]

# ---------------------------------------------------------------------------
# Env keys (subset of upstream types.ts relevant to the Python SDK)
# ---------------------------------------------------------------------------

MIDSCENE_MODEL_NAME = "MIDSCENE_MODEL_NAME"
MIDSCENE_MODEL_API_KEY = "MIDSCENE_MODEL_API_KEY"
MIDSCENE_MODEL_BASE_URL = "MIDSCENE_MODEL_BASE_URL"
MIDSCENE_MODEL_ENDPOINT = "MIDSCENE_MODEL_ENDPOINT"
MIDSCENE_MODEL_FAMILY = "MIDSCENE_MODEL_FAMILY"
MIDSCENE_MODEL_TIMEOUT = "MIDSCENE_MODEL_TIMEOUT"
MIDSCENE_MODEL_TEMPERATURE = "MIDSCENE_MODEL_TEMPERATURE"
MIDSCENE_MODEL_RETRY_COUNT = "MIDSCENE_MODEL_RETRY_COUNT"
MIDSCENE_MODEL_RETRY_INTERVAL = "MIDSCENE_MODEL_RETRY_INTERVAL"
MIDSCENE_MODEL_PROTOCOL = "MIDSCENE_MODEL_PROTOCOL"
MIDSCENE_MODEL_STREAM_MODE = "MIDSCENE_MODEL_STREAM_MODE"
MIDSCENE_MODEL_AUTH_MODE = "MIDSCENE_MODEL_AUTH_MODE"
MIDSCENE_MODEL_INIT_CONFIG_JSON = "MIDSCENE_MODEL_INIT_CONFIG_JSON"
MIDSCENE_MODEL_EXTRA_BODY_JSON = "MIDSCENE_MODEL_EXTRA_BODY_JSON"
MIDSCENE_MODEL_SOCKS_PROXY = "MIDSCENE_MODEL_SOCKS_PROXY"
MIDSCENE_MODEL_HTTP_PROXY = "MIDSCENE_MODEL_HTTP_PROXY"
MIDSCENE_MODEL_REASONING_EFFORT = "MIDSCENE_MODEL_REASONING_EFFORT"
MIDSCENE_MODEL_REASONING_ENABLED = "MIDSCENE_MODEL_REASONING_ENABLED"
MIDSCENE_MODEL_REASONING_BUDGET = "MIDSCENE_MODEL_REASONING_BUDGET"
MIDSCENE_MODEL_RESPONSE_FORMAT = "MIDSCENE_MODEL_RESPONSE_FORMAT"

MIDSCENE_INSIGHT_MODEL_NAME = "MIDSCENE_INSIGHT_MODEL_NAME"
MIDSCENE_INSIGHT_MODEL_API_KEY = "MIDSCENE_INSIGHT_MODEL_API_KEY"
MIDSCENE_INSIGHT_MODEL_BASE_URL = "MIDSCENE_INSIGHT_MODEL_BASE_URL"
MIDSCENE_INSIGHT_MODEL_ENDPOINT = "MIDSCENE_INSIGHT_MODEL_ENDPOINT"
MIDSCENE_INSIGHT_MODEL_FAMILY = "MIDSCENE_INSIGHT_MODEL_FAMILY"
MIDSCENE_INSIGHT_MODEL_TIMEOUT = "MIDSCENE_INSIGHT_MODEL_TIMEOUT"
MIDSCENE_INSIGHT_MODEL_TEMPERATURE = "MIDSCENE_INSIGHT_MODEL_TEMPERATURE"
MIDSCENE_INSIGHT_MODEL_RETRY_COUNT = "MIDSCENE_INSIGHT_MODEL_RETRY_COUNT"
MIDSCENE_INSIGHT_MODEL_RETRY_INTERVAL = "MIDSCENE_INSIGHT_MODEL_RETRY_INTERVAL"
MIDSCENE_INSIGHT_MODEL_PROTOCOL = "MIDSCENE_INSIGHT_MODEL_PROTOCOL"
MIDSCENE_INSIGHT_MODEL_STREAM_MODE = "MIDSCENE_INSIGHT_MODEL_STREAM_MODE"
MIDSCENE_INSIGHT_MODEL_AUTH_MODE = "MIDSCENE_INSIGHT_MODEL_AUTH_MODE"
MIDSCENE_INSIGHT_MODEL_INIT_CONFIG_JSON = "MIDSCENE_INSIGHT_MODEL_INIT_CONFIG_JSON"
MIDSCENE_INSIGHT_MODEL_EXTRA_BODY_JSON = "MIDSCENE_INSIGHT_MODEL_EXTRA_BODY_JSON"
MIDSCENE_INSIGHT_MODEL_SOCKS_PROXY = "MIDSCENE_INSIGHT_MODEL_SOCKS_PROXY"
MIDSCENE_INSIGHT_MODEL_HTTP_PROXY = "MIDSCENE_INSIGHT_MODEL_HTTP_PROXY"
MIDSCENE_INSIGHT_MODEL_REASONING_EFFORT = "MIDSCENE_INSIGHT_MODEL_REASONING_EFFORT"
MIDSCENE_INSIGHT_MODEL_REASONING_ENABLED = "MIDSCENE_INSIGHT_MODEL_REASONING_ENABLED"
MIDSCENE_INSIGHT_MODEL_REASONING_BUDGET = "MIDSCENE_INSIGHT_MODEL_REASONING_BUDGET"
MIDSCENE_INSIGHT_MODEL_RESPONSE_FORMAT = "MIDSCENE_INSIGHT_MODEL_RESPONSE_FORMAT"

MIDSCENE_LOCATE_MODEL_NAME = "MIDSCENE_LOCATE_MODEL_NAME"
MIDSCENE_LOCATE_MODEL_API_KEY = "MIDSCENE_LOCATE_MODEL_API_KEY"
MIDSCENE_LOCATE_MODEL_BASE_URL = "MIDSCENE_LOCATE_MODEL_BASE_URL"
MIDSCENE_LOCATE_MODEL_ENDPOINT = "MIDSCENE_LOCATE_MODEL_ENDPOINT"
MIDSCENE_LOCATE_MODEL_FAMILY = "MIDSCENE_LOCATE_MODEL_FAMILY"
MIDSCENE_LOCATE_MODEL_TIMEOUT = "MIDSCENE_LOCATE_MODEL_TIMEOUT"
MIDSCENE_LOCATE_MODEL_TEMPERATURE = "MIDSCENE_LOCATE_MODEL_TEMPERATURE"
MIDSCENE_LOCATE_MODEL_RETRY_COUNT = "MIDSCENE_LOCATE_MODEL_RETRY_COUNT"
MIDSCENE_LOCATE_MODEL_RETRY_INTERVAL = "MIDSCENE_LOCATE_MODEL_RETRY_INTERVAL"
MIDSCENE_LOCATE_MODEL_PROTOCOL = "MIDSCENE_LOCATE_MODEL_PROTOCOL"
MIDSCENE_LOCATE_MODEL_STREAM_MODE = "MIDSCENE_LOCATE_MODEL_STREAM_MODE"
MIDSCENE_LOCATE_MODEL_AUTH_MODE = "MIDSCENE_LOCATE_MODEL_AUTH_MODE"
MIDSCENE_LOCATE_MODEL_INIT_CONFIG_JSON = "MIDSCENE_LOCATE_MODEL_INIT_CONFIG_JSON"
MIDSCENE_LOCATE_MODEL_EXTRA_BODY_JSON = "MIDSCENE_LOCATE_MODEL_EXTRA_BODY_JSON"
MIDSCENE_LOCATE_MODEL_SOCKS_PROXY = "MIDSCENE_LOCATE_MODEL_SOCKS_PROXY"
MIDSCENE_LOCATE_MODEL_HTTP_PROXY = "MIDSCENE_LOCATE_MODEL_HTTP_PROXY"
MIDSCENE_LOCATE_MODEL_REASONING_EFFORT = "MIDSCENE_LOCATE_MODEL_REASONING_EFFORT"
MIDSCENE_LOCATE_MODEL_REASONING_ENABLED = "MIDSCENE_LOCATE_MODEL_REASONING_ENABLED"
MIDSCENE_LOCATE_MODEL_REASONING_BUDGET = "MIDSCENE_LOCATE_MODEL_REASONING_BUDGET"
MIDSCENE_LOCATE_MODEL_RESPONSE_FORMAT = "MIDSCENE_LOCATE_MODEL_RESPONSE_FORMAT"

MIDSCENE_PLANNING_MODEL_NAME = "MIDSCENE_PLANNING_MODEL_NAME"
MIDSCENE_PLANNING_MODEL_API_KEY = "MIDSCENE_PLANNING_MODEL_API_KEY"
MIDSCENE_PLANNING_MODEL_BASE_URL = "MIDSCENE_PLANNING_MODEL_BASE_URL"
MIDSCENE_PLANNING_MODEL_ENDPOINT = "MIDSCENE_PLANNING_MODEL_ENDPOINT"
MIDSCENE_PLANNING_MODEL_FAMILY = "MIDSCENE_PLANNING_MODEL_FAMILY"
MIDSCENE_PLANNING_MODEL_TIMEOUT = "MIDSCENE_PLANNING_MODEL_TIMEOUT"
MIDSCENE_PLANNING_MODEL_TEMPERATURE = "MIDSCENE_PLANNING_MODEL_TEMPERATURE"
MIDSCENE_PLANNING_MODEL_RETRY_COUNT = "MIDSCENE_PLANNING_MODEL_RETRY_COUNT"
MIDSCENE_PLANNING_MODEL_RETRY_INTERVAL = "MIDSCENE_PLANNING_MODEL_RETRY_INTERVAL"
MIDSCENE_PLANNING_MODEL_PROTOCOL = "MIDSCENE_PLANNING_MODEL_PROTOCOL"
MIDSCENE_PLANNING_MODEL_STREAM_MODE = "MIDSCENE_PLANNING_MODEL_STREAM_MODE"
MIDSCENE_PLANNING_MODEL_AUTH_MODE = "MIDSCENE_PLANNING_MODEL_AUTH_MODE"
MIDSCENE_PLANNING_MODEL_INIT_CONFIG_JSON = "MIDSCENE_PLANNING_MODEL_INIT_CONFIG_JSON"
MIDSCENE_PLANNING_MODEL_EXTRA_BODY_JSON = "MIDSCENE_PLANNING_MODEL_EXTRA_BODY_JSON"
MIDSCENE_PLANNING_MODEL_SOCKS_PROXY = "MIDSCENE_PLANNING_MODEL_SOCKS_PROXY"
MIDSCENE_PLANNING_MODEL_HTTP_PROXY = "MIDSCENE_PLANNING_MODEL_HTTP_PROXY"
MIDSCENE_PLANNING_MODEL_REASONING_EFFORT = "MIDSCENE_PLANNING_MODEL_REASONING_EFFORT"
MIDSCENE_PLANNING_MODEL_REASONING_ENABLED = "MIDSCENE_PLANNING_MODEL_REASONING_ENABLED"
MIDSCENE_PLANNING_MODEL_REASONING_BUDGET = "MIDSCENE_PLANNING_MODEL_REASONING_BUDGET"
MIDSCENE_PLANNING_MODEL_RESPONSE_FORMAT = "MIDSCENE_PLANNING_MODEL_RESPONSE_FORMAT"

# Deprecated vision-mode switches (legacy → model family)
MIDSCENE_USE_VLM_UI_TARS = "MIDSCENE_USE_VLM_UI_TARS"
MIDSCENE_USE_QWEN_VL = "MIDSCENE_USE_QWEN_VL"
MIDSCENE_USE_QWEN3_VL = "MIDSCENE_USE_QWEN3_VL"
MIDSCENE_USE_DOUBAO_VISION = "MIDSCENE_USE_DOUBAO_VISION"
MIDSCENE_USE_GEMINI = "MIDSCENE_USE_GEMINI"
MIDSCENE_USE_VL_MODEL = "MIDSCENE_USE_VL_MODEL"

# Deprecated generic keys kept for backward compatibility of this SDK
MIDSCENE_AI_MODEL = "MIDSCENE_AI_MODEL"
MIDSCENE_AI_API_KEY = "MIDSCENE_AI_API_KEY"
MIDSCENE_AI_BASE_URL = "MIDSCENE_AI_BASE_URL"

OPENAI_API_KEY = "OPENAI_API_KEY"
OPENAI_BASE_URL = "OPENAI_BASE_URL"

MIDSCENE_PREFERRED_LANGUAGE = "MIDSCENE_PREFERRED_LANGUAGE"
MIDSCENE_RUN_DIR = "MIDSCENE_RUN_DIR"
MIDSCENE_CACHE = "MIDSCENE_CACHE"
MIDSCENE_REPLANNING_CYCLE_LIMIT = "MIDSCENE_REPLANNING_CYCLE_LIMIT"
MIDSCENE_LOCATE_MODEL_STREAM_MODE = "MIDSCENE_LOCATE_MODEL_STREAM_MODE"
MIDSCENE_PLANNING_MODEL_STREAM_MODE = "MIDSCENE_PLANNING_MODEL_STREAM_MODE"
MIDSCENE_INSIGHT_MODEL_STREAM_MODE = "MIDSCENE_INSIGHT_MODEL_STREAM_MODE"
MIDSCENE_LOCATE_MODEL_AUTH_MODE = "MIDSCENE_LOCATE_MODEL_AUTH_MODE"

TIntent = str  # 'insight' | 'planning' | 'locate' | 'default'
TModelFamily = str
TModelProtocol = str  # 'openai-chat' | 'openai-responses'
TModelStreamMode = str  # 'stream' | 'non-stream'

DEFAULT_TIMEOUT_SECONDS = 180  # upstream: 180000 ms
DEFAULT_RETRY_INTERVAL_MS = 2000

# ---------------------------------------------------------------------------
# Per-intent model config key maps (upstream constants.ts)
# ---------------------------------------------------------------------------

DEFAULT_MODEL_CONFIG_KEYS = {
    "modelName": MIDSCENE_MODEL_NAME,
    "openaiApiKey": MIDSCENE_MODEL_API_KEY,
    "openaiBaseURL": MIDSCENE_MODEL_BASE_URL,
    "endpoint": MIDSCENE_MODEL_ENDPOINT,
    "modelFamily": MIDSCENE_MODEL_FAMILY,
    "timeout": MIDSCENE_MODEL_TIMEOUT,
    "temperature": MIDSCENE_MODEL_TEMPERATURE,
    "retryCount": MIDSCENE_MODEL_RETRY_COUNT,
    "retryInterval": MIDSCENE_MODEL_RETRY_INTERVAL,
    "protocol": MIDSCENE_MODEL_PROTOCOL,
    "streamMode": MIDSCENE_MODEL_STREAM_MODE,
    "authMode": MIDSCENE_MODEL_AUTH_MODE,
    "openaiExtraConfig": MIDSCENE_MODEL_INIT_CONFIG_JSON,
    "extraBody": MIDSCENE_MODEL_EXTRA_BODY_JSON,
    "socksProxy": MIDSCENE_MODEL_SOCKS_PROXY,
    "httpProxy": MIDSCENE_MODEL_HTTP_PROXY,
    "reasoningEffort": MIDSCENE_MODEL_REASONING_EFFORT,
    "reasoningEnabled": MIDSCENE_MODEL_REASONING_ENABLED,
    "reasoningBudget": MIDSCENE_MODEL_REASONING_BUDGET,
    "responseFormat": MIDSCENE_MODEL_RESPONSE_FORMAT,
}

LOCATE_MODEL_CONFIG_KEYS = {
    "modelName": MIDSCENE_LOCATE_MODEL_NAME,
    "openaiApiKey": MIDSCENE_LOCATE_MODEL_API_KEY,
    "openaiBaseURL": MIDSCENE_LOCATE_MODEL_BASE_URL,
    "endpoint": MIDSCENE_LOCATE_MODEL_ENDPOINT,
    "modelFamily": MIDSCENE_LOCATE_MODEL_FAMILY,
    "timeout": MIDSCENE_LOCATE_MODEL_TIMEOUT,
    "temperature": MIDSCENE_LOCATE_MODEL_TEMPERATURE,
    "retryCount": MIDSCENE_LOCATE_MODEL_RETRY_COUNT,
    "retryInterval": MIDSCENE_LOCATE_MODEL_RETRY_INTERVAL,
    "protocol": MIDSCENE_LOCATE_MODEL_PROTOCOL,
    "streamMode": MIDSCENE_LOCATE_MODEL_STREAM_MODE,
    "authMode": MIDSCENE_LOCATE_MODEL_AUTH_MODE,
    "openaiExtraConfig": MIDSCENE_LOCATE_MODEL_INIT_CONFIG_JSON,
    "extraBody": MIDSCENE_LOCATE_MODEL_EXTRA_BODY_JSON,
    "socksProxy": MIDSCENE_LOCATE_MODEL_SOCKS_PROXY,
    "httpProxy": MIDSCENE_LOCATE_MODEL_HTTP_PROXY,
    "reasoningEffort": MIDSCENE_LOCATE_MODEL_REASONING_EFFORT,
    "reasoningEnabled": MIDSCENE_LOCATE_MODEL_REASONING_ENABLED,
    "reasoningBudget": MIDSCENE_LOCATE_MODEL_REASONING_BUDGET,
    "responseFormat": MIDSCENE_LOCATE_MODEL_RESPONSE_FORMAT,
}

INSIGHT_MODEL_CONFIG_KEYS = {
    "modelName": MIDSCENE_INSIGHT_MODEL_NAME,
    "openaiApiKey": MIDSCENE_INSIGHT_MODEL_API_KEY,
    "openaiBaseURL": MIDSCENE_INSIGHT_MODEL_BASE_URL,
    "endpoint": MIDSCENE_INSIGHT_MODEL_ENDPOINT,
    "modelFamily": MIDSCENE_INSIGHT_MODEL_FAMILY,
    "timeout": MIDSCENE_INSIGHT_MODEL_TIMEOUT,
    "temperature": MIDSCENE_INSIGHT_MODEL_TEMPERATURE,
    "retryCount": MIDSCENE_INSIGHT_MODEL_RETRY_COUNT,
    "retryInterval": MIDSCENE_INSIGHT_MODEL_RETRY_INTERVAL,
    "protocol": MIDSCENE_INSIGHT_MODEL_PROTOCOL,
    "streamMode": MIDSCENE_INSIGHT_MODEL_STREAM_MODE,
    "authMode": MIDSCENE_INSIGHT_MODEL_AUTH_MODE,
    "openaiExtraConfig": MIDSCENE_INSIGHT_MODEL_INIT_CONFIG_JSON,
    "extraBody": MIDSCENE_INSIGHT_MODEL_EXTRA_BODY_JSON,
    "socksProxy": MIDSCENE_INSIGHT_MODEL_SOCKS_PROXY,
    "httpProxy": MIDSCENE_INSIGHT_MODEL_HTTP_PROXY,
    "reasoningEffort": MIDSCENE_INSIGHT_MODEL_REASONING_EFFORT,
    "reasoningEnabled": MIDSCENE_INSIGHT_MODEL_REASONING_ENABLED,
    "reasoningBudget": MIDSCENE_INSIGHT_MODEL_REASONING_BUDGET,
    "responseFormat": MIDSCENE_INSIGHT_MODEL_RESPONSE_FORMAT,
}

PLANNING_MODEL_CONFIG_KEYS = {
    "modelName": MIDSCENE_PLANNING_MODEL_NAME,
    "openaiApiKey": MIDSCENE_PLANNING_MODEL_API_KEY,
    "openaiBaseURL": MIDSCENE_PLANNING_MODEL_BASE_URL,
    "endpoint": MIDSCENE_PLANNING_MODEL_ENDPOINT,
    "modelFamily": MIDSCENE_PLANNING_MODEL_FAMILY,
    "timeout": MIDSCENE_PLANNING_MODEL_TIMEOUT,
    "temperature": MIDSCENE_PLANNING_MODEL_TEMPERATURE,
    "retryCount": MIDSCENE_PLANNING_MODEL_RETRY_COUNT,
    "retryInterval": MIDSCENE_PLANNING_MODEL_RETRY_INTERVAL,
    "protocol": MIDSCENE_PLANNING_MODEL_PROTOCOL,
    "streamMode": MIDSCENE_PLANNING_MODEL_STREAM_MODE,
    "authMode": MIDSCENE_PLANNING_MODEL_AUTH_MODE,
    "openaiExtraConfig": MIDSCENE_PLANNING_MODEL_INIT_CONFIG_JSON,
    "extraBody": MIDSCENE_PLANNING_MODEL_EXTRA_BODY_JSON,
    "socksProxy": MIDSCENE_PLANNING_MODEL_SOCKS_PROXY,
    "httpProxy": MIDSCENE_PLANNING_MODEL_HTTP_PROXY,
    "reasoningEffort": MIDSCENE_PLANNING_MODEL_REASONING_EFFORT,
    "reasoningEnabled": MIDSCENE_PLANNING_MODEL_REASONING_ENABLED,
    "reasoningBudget": MIDSCENE_PLANNING_MODEL_REASONING_BUDGET,
    "responseFormat": MIDSCENE_PLANNING_MODEL_RESPONSE_FORMAT,
}

KEYS_MAP: Dict[TIntent, Dict[str, str]] = {
    "locate": LOCATE_MODEL_CONFIG_KEYS,
    "insight": INSIGHT_MODEL_CONFIG_KEYS,
    "planning": PLANNING_MODEL_CONFIG_KEYS,
    "default": DEFAULT_MODEL_CONFIG_KEYS,
}

# Legacy keys honored for the default slot (this repo's previous env names and
# upstream's deprecated OpenAI-SDK style names)
LEGACY_DEFAULT_KEYS = {
    "openaiApiKey": [OPENAI_API_KEY, MIDSCENE_AI_API_KEY],
    "openaiBaseURL": [OPENAI_BASE_URL, MIDSCENE_AI_BASE_URL],
    "modelName": [MIDSCENE_AI_MODEL],
}


def model_family_required_for_locate_message(slot: Optional[str] = None) -> str:
    role = "Locate" if slot == "locate" else "Default"
    config_key = (
        "MIDSCENE_LOCATE_MODEL_FAMILY" if slot == "locate" else "MIDSCENE_MODEL_FAMILY"
    )
    return (
        f"{role} model family is required for locate. Configure {config_key} so "
        f"Midscene can parse locate coordinates correctly. {MODEL_CONFIG_DOC_URL}"
    )


def planning_model_family_required_for_locate_message(slot: Optional[str] = None) -> str:
    if slot == "planning":
        return (
            "Planning model family is required because aiAct is asking the planning "
            "model to return locate coordinates. Configure MIDSCENE_PLANNING_MODEL_FAMILY "
            "for the planning model, or remove the separate planning model config and "
            f"configure MIDSCENE_MODEL_FAMILY on the default model. {MODEL_CONFIG_DOC_URL}"
        )
    return (
        "Default model family is required because aiAct is asking the default model "
        "to return locate coordinates during planning. Configure MIDSCENE_MODEL_FAMILY "
        f"so Midscene can parse planning locate coordinates correctly. {MODEL_CONFIG_DOC_URL}"
    )


def legacy_config_to_model_family(provider: Dict[str, Optional[str]]) -> Optional[str]:
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


def get_uitars_model_version(model_family: Optional[str]) -> Optional[str]:
    if model_family == "vlm-ui-tars":
        return "1.0"
    if model_family in ("vlm-ui-tars-doubao", "vlm-ui-tars-doubao-1.5"):
        return "doubao-1.5-20B"
    return None


def validate_model_family(model_family: Optional[str]) -> None:
    if model_family and model_family not in MODEL_FAMILY_VALUES:
        raise ValueError(
            f"Invalid MIDSCENE_MODEL_FAMILY value: {model_family}. Current version "
            f"accepts the following model families: {', '.join(MODEL_FAMILY_VALUES)}. "
            f"You can also visit {MODEL_CONFIG_DOC_URL} for the latest configuration."
        )


def get_model_description(
    model_family: Optional[str], ui_tars_model_version: Optional[str]
) -> str:
    if ui_tars_model_version:
        return f"UI-TARS={ui_tars_model_version}"
    if model_family:
        return f"{model_family} mode"
    return ""


def _parse_temperature(raw: Optional[str]) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        temperature = float(raw)
    except ValueError:
        return None
    return temperature if temperature == temperature else None  # NaN check


def _parse_number_env(
    raw: Optional[str],
    key: str,
    default: Optional[float],
    minimum: Optional[float] = 0,
) -> Optional[float]:
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{key} must be a finite number, got {raw!r}")
    if value != value:  # NaN
        raise ValueError(f"{key} must be a finite number, got {raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}, got {value}")
    return value


def _parse_json_env(key: str, value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse {key} as a JSON. {e}")
    if not isinstance(parsed, dict):
        return None
    return parsed


def parse_openai_sdk_config(
    keys: Dict[str, str],
    provider: Dict[str, Optional[str]],
    use_legacy_logic: bool = False,
) -> Dict:
    """Parse a per-intent model configuration from an env-style key/value map.

    Ported from upstream parse-model-config.ts (parseOpenaiSdkConfig).
    """
    def pick(field: str) -> Optional[str]:
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
            f'{keys["protocol"]} must be one of: openai-chat, openai-responses. '
            f"Got: {protocol}"
        )

    stream_mode = (pick("streamMode") or "non-stream").strip() or "non-stream"
    if stream_mode not in ("stream", "non-stream"):
        raise ValueError(
            f'Invalid {keys["streamMode"]}: "{stream_mode}". '
            'Expected "stream" or "non-stream".'
        )

    timeout = _parse_number_env(pick("timeout"), keys["timeout"], None)

    retry_count_raw = pick("retryCount")
    retry_count = 1
    if retry_count_raw:
        try:
            retry_count = int(float(retry_count_raw))
        except ValueError:
            retry_count = 1
        if retry_count < 0:
            raise ValueError(
                f'{keys["retryCount"]} must be non-negative, got {retry_count}'
            )

    retry_interval = _parse_number_env(
        pick("retryInterval"), keys["retryInterval"], DEFAULT_RETRY_INTERVAL_MS
    )

    reasoning_effort = (pick("reasoningEffort") or "").strip() or None

    reasoning_enabled_raw = (pick("reasoningEnabled") or "").strip().lower()
    reasoning_enabled: Optional[Union[bool, str]] = None
    if reasoning_enabled_raw in ("true", "1"):
        reasoning_enabled = True
    elif reasoning_enabled_raw in ("false", "0"):
        reasoning_enabled = False
    elif reasoning_enabled_raw == "default":
        reasoning_enabled = "default"

    reasoning_budget_raw = (pick("reasoningBudget") or "").strip()
    reasoning_budget: Optional[int] = None
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
            f'{keys["responseFormat"]} must be one of: none, auto. Got: {response_format}'
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
    intent: TIntent, config_map: Dict[str, Optional[str]]
) -> Optional[Dict]:
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


class ModelConfigManager:
    """Resolve per-intent model configs (default/locate/insight/planning).

    Ported from upstream model-config-manager.ts. Each intent slot falls back to
    the default slot when its dedicated env keys are absent.
    """

    def __init__(
        self,
        model_config: Optional[Dict[str, Union[str, int, float]]] = None,
        env_provider: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.model_config = model_config
        self.env_provider = env_provider
        self._model_config_map: Optional[Dict[TIntent, Dict]] = None
        self._isolated = model_config is not None

    @property
    def isolated_mode(self) -> bool:
        return self._isolated

    def _get_env(self, key: str) -> Optional[str]:
        if self.env_provider is not None:
            return self.env_provider.get(key)
        return os.environ.get(key)

    def _all_env(self) -> Dict[str, Optional[str]]:
        if self.env_provider is not None:
            return dict(self.env_provider)
        return dict(os.environ)

    def _initialize(self) -> None:
        if self._model_config_map is not None:
            return

        if self.model_config is not None:
            config_map: Dict[str, Optional[str]] = {
                str(k): None if v is None else str(v)
                for k, v in self.model_config.items()
            }
        else:
            config_map = self._all_env()

        default_config = decide_model_config_from_intent_config("default", config_map)
        if default_config is None:
            raise ValueError(
                "Model configuration is incomplete: model name (MIDSCENE_MODEL_NAME) "
                f"is required. See {MODEL_CONFIG_DOC_URL}"
            )

        insight_config = decide_model_config_from_intent_config("insight", config_map)
        planning_config = decide_model_config_from_intent_config(
            "planning", config_map
        )
        locate_config = decide_model_config_from_intent_config("locate", config_map)

        def build(intent: TIntent, specific: Optional[Dict]) -> Dict:
            config = dict(specific if specific is not None else default_config)
            config["intent"] = intent
            config["slot"] = intent if specific is not None else "default"
            return config

        self._model_config_map = {
            "default": build("default", default_config),
            "locate": build("locate", locate_config),
            "insight": build("insight", insight_config),
            "planning": build("planning", planning_config),
        }

    def get_model_config(self, intent: TIntent) -> Dict:
        self._initialize()
        assert self._model_config_map is not None
        return self._model_config_map[intent]

    def clear_model_config_map(self) -> None:
        if self._isolated:
            raise RuntimeError(
                "ModelConfigManager work in isolated mode, so clear_model_config_map "
                "should not be called"
            )
        self._model_config_map = None

    def throw_error_if_non_vl_model(self) -> None:
        model_config = self.get_model_config("locate")
        if not model_config.get("modelFamily"):
            raise ValueError(model_family_required_for_locate_message(model_config["slot"]))

    def get_upload_test_server_url(self) -> Optional[str]:
        model_config = self.get_model_config("default")
        extra = model_config.get("openaiExtraConfig") or {}
        return extra.get("REPORT_SERVER_URL")


_global_model_config_manager = ModelConfigManager()


def get_global_model_config_manager() -> ModelConfigManager:
    return _global_model_config_manager


def reset_global_model_config() -> None:
    """Re-read env on next use (used after override_ai_config)."""
    _global_model_config_manager.clear_model_config_map()


def override_ai_config(
    new_config: Dict[str, Union[str, int, float]], extend_mode: bool = False
) -> None:
    """Override global model config (mirrors upstream overrideAIConfig)."""
    global _global_model_config_manager
    if extend_mode:
        merged = dict(_global_model_config_manager.model_config or {})
        merged.update(new_config)
        _global_model_config_manager = ModelConfigManager(merged)
    else:
        _global_model_config_manager = ModelConfigManager(dict(new_config))


def get_midscene_run_dir(sub_dir: str = "") -> str:
    """Return (and create) the midscene output directory (MIDSCENE_RUN_DIR)."""
    root = os.environ.get(MIDSCENE_RUN_DIR) or str(
        Path.cwd() / "midscene_run"
    )
    target = Path(root) / sub_dir if sub_dir else Path(root)
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def get_preferred_language() -> str:
    prefer = os.environ.get(MIDSCENE_PREFERRED_LANGUAGE)
    if prefer:
        return prefer

    is_china = False
    if _HAS_ZONEINFO:
        try:
            tz = time.tzname
            _ = tz  # time.tzname alone is insufficient; try env TZ first
        except Exception:  # pragma: no cover
            pass
    tz_env = os.environ.get("TZ", "")
    # Match upstream behaviour: China timezone defaults to Chinese prompts.
    if tz_env == "Asia/Shanghai":
        is_china = True
    else:
        try:
            import datetime as _dt

            now = _dt.datetime.now().astimezone()
            offset = now.utcoffset() or _dt.timedelta(0)
            # CST (China Standard Time) is UTC+8 with no DST
            is_china = offset == _dt.timedelta(hours=8)
        except Exception:  # pragma: no cover
            is_china = False
    return "Chinese" if is_china else "English"


def is_cache_enabled() -> bool:
    value = os.environ.get(MIDSCENE_CACHE, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_replanning_cycle_limit(default: int = 20) -> int:
    raw = os.environ.get(MIDSCENE_REPLANNING_CYCLE_LIMIT)
    if not raw:
        return default
    try:
        value = int(float(raw))
        return value if value > 0 else default
    except ValueError:
        return default
