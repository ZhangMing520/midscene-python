"""Model adapter registry and runtime (upstream ai-model/models/registry.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.model_adapter.resolve import ModelAdapter
from midscene.core.ai_model.model_adapter.types import ModelRuntime
from midscene.core.ai_model.models.ant_ling.adapter import (
    ANT_LING_LOCATE_FORMAT,
    _build_ant_ling_params,
    ant_ling_adapters,
)
from midscene.core.ai_model.models.auto_glm.adapter import (
    _build_auto_glm_params,
    auto_glm_adapters,
)
from midscene.core.ai_model.models.deepseek.adapter import (
    DEEPSEEK_ELEMENT_LOCATE_FORMAT,
    DEEPSEEK_ELEMENT_LOCATE_PROTOCOL,
    DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT,
    DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL,
    _build_deepseek_params,
    deep_seek_adapters,
)
from midscene.core.ai_model.models.default import (
    DEFAULT_LOCATE_FORMAT,
    default_open_ai_compatible_adapter_config,
)
from midscene.core.ai_model.models.doubao import (
    DOUBAO_LOCATE_FORMAT,
    _build_doubao_params,
    doubao_adapters,
)
from midscene.core.ai_model.models.gemini import (
    GEMINI_LOCATE_FORMAT,
    _build_gemini_params,
    extract_gemini_content_and_reasoning,
    gemini_adapters,
)
from midscene.core.ai_model.models.glm import (
    GLM_LOCATE_FORMAT,
    _build_glm_params,
    glm_adapters,
)
from midscene.core.ai_model.models.gpt import (
    GPT_LOCATE_FORMAT,
    _build_gpt5_chat_params,
    _build_gpt5_responses_params,
    _build_gpt6_chat_params,
    _build_gpt6_responses_params,
    gpt_adapters,
)
from midscene.core.ai_model.models.jev.adapter import (
    _jev_boolean_fn,
    _jev_locate_fn,
    jev_adapters,
)
from midscene.core.ai_model.models.kimi import (
    KIMI_LOCATE_FORMAT,
    _build_kimi3_params,
    _build_kimi_params,
    kimi_adapters,
)
from midscene.core.ai_model.models.mimo import (
    _build_mimo_params,
    mimo_adapters,
)
from midscene.core.ai_model.models.qwen import (
    QWEN25_LOCATE_FORMAT,
    QWEN3_LOCATE_FORMAT,
    QWEN4_LOCATE_FORMAT,
    _build_qwen25_params,
    _build_qwen3_params,
    _build_qwen4_params,
    _build_qwen_params,
    _parse_qwen_locate_json,
    qwen_adapters,
)
from midscene.core.ai_model.models.stepfun import (
    STEP_LOCATE_FORMAT,
    _build_step_params,
    step_fun_adapters,
)
from midscene.core.ai_model.models.tencent_hy import (
    TENCENT_HY_LOCATE_FORMAT,
    _build_tencent_hy_params,
    tencent_hy_adapters,
)
from midscene.core.ai_model.models.ui_tars.adapter import (
    UI_TARS_LOCATE_FORMAT,
    _build_ui_tars_params,
    ui_tars_adapters,
)
from midscene.core.ai_model.models.utils.intent import is_locate_intent

_ALL_PROTOCOLS = ["openai-chat", "openai-responses"]


MODEL_ADAPTER_CONFIGS = {
    **ant_ling_adapters,
    **step_fun_adapters,
    **jev_adapters,
    **qwen_adapters,
    **deep_seek_adapters,
    **doubao_adapters,
    **gemini_adapters,
    **ui_tars_adapters,
    **glm_adapters,
    **auto_glm_adapters,
    **gpt_adapters,
    **tencent_hy_adapters,
    **kimi_adapters,
    **mimo_adapters,
}


def _default_adapter() -> ModelAdapter:
    # Default adapter recovers from empty content via reasoning_content because
    # many OpenAI-compatible servers emit useful output there.
    return ModelAdapter(
        family="default",
        unsupported_user_config=[
            "reasoningEnabled",
            "reasoningEffort",
            "reasoningBudget",
        ],
        use_reasoning_as_content_fallback=(
            default_open_ai_compatible_adapter_config["chat_completion"][
                "use_reasoning_as_content_fallback"
            ]
        ),
    )


def _qwen3_adapter() -> ModelAdapter:
    return ModelAdapter(
        family="qwen3-vl",
        build_chat_completion_params=_build_qwen_params,
        unsupported_user_config=["reasoningEffort"],
        reasoning_content_keys=["reasoning_content", "reasoning"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=QWEN3_LOCATE_FORMAT,
    )


def _qwen3_text_adapter() -> ModelAdapter:
    return ModelAdapter(
        family="qwen3",
        build_chat_completion_params=_build_qwen3_params,
        reasoning_content_keys=["reasoning_content", "reasoning"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=QWEN3_LOCATE_FORMAT,
        json_parser=_parse_qwen_locate_json,
    )


def _qwen4_adapter() -> ModelAdapter:
    return ModelAdapter(
        family="qwen4",
        build_chat_completion_params=_build_qwen4_params,
        reasoning_content_keys=["reasoning_content", "reasoning"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=QWEN4_LOCATE_FORMAT,
        json_parser=_parse_qwen_locate_json,
    )


def _adapter_registry() -> Dict[str, ModelAdapter]:
    qwen3 = _qwen3_adapter()
    ui_tars_doubao = ModelAdapter(
        family="vlm-ui-tars-doubao",
        build_chat_completion_params=_build_ui_tars_params,
        unsupported_user_config=[
            "reasoningEnabled",
            "reasoningEffort",
            "reasoningBudget",
        ],
        locate_element_format=UI_TARS_LOCATE_FORMAT,
        replanning_cycle_limit=40,
        cache_enabled=False,
        planning_kind="custom",
    )
    deepseek = ModelAdapter(
        family="deepseek",
        build_chat_completion_params=_build_deepseek_params,
        unsupported_user_config=["reasoningBudget"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=DEEPSEEK_ELEMENT_LOCATE_FORMAT,
        element_protocol=DEEPSEEK_ELEMENT_LOCATE_PROTOCOL,
        search_area_locate_format=DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT,
        search_area_protocol=DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL,
    )
    gemini = ModelAdapter(
        family="gemini",
        build_chat_completion_params=_build_gemini_params,
        unsupported_user_config=["reasoningBudget"],
        locate_element_format=GEMINI_LOCATE_FORMAT,
        extract_content_and_reasoning=extract_gemini_content_and_reasoning,
    )
    doubao = ModelAdapter(
        family="doubao-seed",
        build_chat_completion_params=_build_doubao_params,
        unsupported_user_config=["reasoningBudget"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=DOUBAO_LOCATE_FORMAT,
    )

    registry: Dict[str, ModelAdapter] = {
        "default": _default_adapter(),
        "qwen2.5-vl": ModelAdapter(
            family="qwen2.5-vl",
            build_chat_completion_params=_build_qwen25_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            locate_element_format=QWEN25_LOCATE_FORMAT,
            image_pad_block_size=28,
        ),
        "qwen3-vl": qwen3,
        "qwen3": _qwen3_text_adapter(),
        "qwen3.5": _qwen3_text_adapter(),
        "qwen3.6": _qwen3_text_adapter(),
        "qwen4": _qwen4_adapter(),
        "step": ModelAdapter(
            family="step",
            build_chat_completion_params=_build_step_params,
            supported_protocols=["openai-chat"],
            reasoning_content_keys=["reasoning", "reasoning_content"],
            locate_element_format=STEP_LOCATE_FORMAT,
        ),
        "tencent-hy": ModelAdapter(
            family="tencent-hy",
            build_chat_completion_params=_build_tencent_hy_params,
            unsupported_user_config=["reasoningBudget"],
            locate_element_format=TENCENT_HY_LOCATE_FORMAT,
        ),
        "gpt-5": ModelAdapter(
            family="gpt-5",
            build_chat_completion_params=_build_gpt5_chat_params,
            build_responses_params=_build_gpt5_responses_params,
            responses_unsupported_user_config=["reasoningBudget"],
            unsupported_user_config=["reasoningBudget"],
            supported_protocols=_ALL_PROTOCOLS,
            locate_element_format=GPT_LOCATE_FORMAT,
        ),
        "gpt-6": ModelAdapter(
            family="gpt-6",
            build_chat_completion_params=_build_gpt6_chat_params,
            build_responses_params=_build_gpt6_responses_params,
            responses_unsupported_user_config=["temperature", "reasoningBudget"],
            unsupported_user_config=["temperature", "reasoningBudget"],
            supported_protocols=_ALL_PROTOCOLS,
            locate_element_format=GPT_LOCATE_FORMAT,
        ),
        "doubao-seed": doubao,
        "doubao-vision": doubao,
        "gemini": gemini,
        "glm-v": ModelAdapter(
            family="glm-v",
            build_chat_completion_params=_build_glm_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=GLM_LOCATE_FORMAT,
        ),
        "kimi": ModelAdapter(
            family="kimi",
            build_chat_completion_params=_build_kimi_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=KIMI_LOCATE_FORMAT,
        ),
        "kimi3": ModelAdapter(
            family="kimi3",
            build_chat_completion_params=_build_kimi3_params,
            unsupported_user_config=["reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=KIMI_LOCATE_FORMAT,
            replay_raw_assistant_message=True,
        ),
        "xiaomi-mimo": ModelAdapter(
            family="xiaomi-mimo",
            build_chat_completion_params=_build_mimo_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=DEFAULT_LOCATE_FORMAT,
        ),
        "deepseek": deepseek,
        "ant-ling": ModelAdapter(
            family="ant-ling",
            build_chat_completion_params=_build_ant_ling_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            supported_protocols=["openai-chat"],
            locate_element_format=ANT_LING_LOCATE_FORMAT,
        ),
        "vlm-ui-tars": ModelAdapter(
            family="vlm-ui-tars",
            build_chat_completion_params=_build_ui_tars_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            locate_element_format=UI_TARS_LOCATE_FORMAT,
            replanning_cycle_limit=40,
            cache_enabled=False,
            planning_kind="custom",
        ),
        "vlm-ui-tars-doubao": ui_tars_doubao,
        "vlm-ui-tars-doubao-1.5": ui_tars_doubao,
        "auto-glm": ModelAdapter(
            family="auto-glm",
            build_chat_completion_params=_build_auto_glm_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            replanning_cycle_limit=100,
            cache_enabled=False,
            planning_kind="custom",
            locate_kind="custom",
        ),
        "auto-glm-multilingual": ModelAdapter(
            family="auto-glm-multilingual",
            build_chat_completion_params=_build_auto_glm_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            replanning_cycle_limit=100,
            cache_enabled=False,
            planning_kind="custom",
            locate_kind="custom",
        ),
        "jev": ModelAdapter(
            family="jev",
            allowed_task_types=["locate", "boolean", "planning"],
            supported_protocols=[],
            locate_kind="custom",
            locate_fn=_jev_locate_fn(),
            planning_kind="custom",
            cache_enabled=False,
            replanning_cycle_limit=20,
            insight_boolean_fn=_jev_boolean_fn(),
        ),
    }
    return registry


_ADAPTER_CACHE: Dict[str, ModelAdapter] = {}


_REGISTRY: Optional[Dict[str, ModelAdapter]] = None


def get_model_adapter(model_family: Optional[str] = None) -> ModelAdapter:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _adapter_registry()
        # Bind custom planners (UI-TARS / Auto-GLM) to their adapters on first use.
        from midscene.core.ai_model.workflows.planning.custom_planning import register_custom_planners

        register_custom_planners()
    cache_key = model_family or "default"
    adapter = _ADAPTER_CACHE.get(cache_key)
    if adapter is not None:
        return adapter
    if model_family:
        adapter = _REGISTRY.get(model_family)
        if adapter is None:
            raise ValueError(
                f"No model adapter registered for modelFamily: {model_family}"
            )
    else:
        adapter = _REGISTRY["default"]
    _ADAPTER_CACHE[cache_key] = adapter
    return adapter


def get_model_runtime(config: Dict[str, Any]) -> ModelRuntime:
    return ModelRuntime(
        config=config, adapter=get_model_adapter(config.get("modelFamily"))
    )


__all__ = [
    "MODEL_ADAPTER_CONFIGS",
    "ModelAdapter",
    "ModelRuntime",
    "get_model_adapter",
    "get_model_runtime",
    "is_locate_intent",
]
