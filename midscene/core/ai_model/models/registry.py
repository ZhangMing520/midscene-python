"""Model adapter registry and runtime (upstream ai-model/models/registry.ts)."""

from typing import Any, Callable, Dict, List, Optional
import uuid

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_codec,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)
from midscene.core.ai_model.models.ant_ling import (
    ANT_LING_LOCATE_FORMAT,
    _build_ant_ling_params,
)
from midscene.core.ai_model.models.auto_glm import (
    _build_auto_glm_params,
)
from midscene.core.ai_model.models.deepseek import (
    DEEPSEEK_ELEMENT_LOCATE_FORMAT,
    DEEPSEEK_ELEMENT_LOCATE_PROTOCOL,
    DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT,
    DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL,
    _build_deepseek_params,
)
from midscene.core.ai_model.models.default import (
    DEFAULT_LOCATE_FORMAT,
    _build_default_params,
)
from midscene.core.ai_model.models.doubao import (
    DOUBAO_LOCATE_FORMAT,
    _build_doubao_params,
)
from midscene.core.ai_model.models.gemini import (
    GEMINI_LOCATE_FORMAT,
    _build_gemini_params,
)
from midscene.core.ai_model.models.glm import (
    GLM_LOCATE_FORMAT,
    _build_glm_params,
)
from midscene.core.ai_model.models.gpt import (
    GPT_LOCATE_FORMAT,
    _build_gpt5_chat_params,
    _build_gpt5_responses_params,
    _build_gpt6_chat_params,
    _build_gpt6_responses_params,
)
from midscene.core.ai_model.models.jev.adapter import (
    _jev_boolean_fn,
    _jev_locate_fn,
)
from midscene.core.ai_model.models.kimi import (
    KIMI_LOCATE_FORMAT,
    _build_kimi3_params,
    _build_kimi_params,
)
from midscene.core.ai_model.models.mimo import (
    _build_mimo_params,
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
)
from midscene.core.ai_model.models.stepfun import (
    STEP_LOCATE_FORMAT,
    _build_step_params,
)
from midscene.core.ai_model.models.tencent_hy import (
    TENCENT_HY_LOCATE_FORMAT,
    _build_tencent_hy_params,
)
from midscene.core.ai_model.models.ui_tars import (
    UI_TARS_LOCATE_FORMAT,
    _build_ui_tars_params,
)
from midscene.core.ai_model.models.utils.intent import is_locate_intent

_ALL_PROTOCOLS = ["openai-chat", "openai-responses"]


class ModelAdapter:
    """Resolved per-family adapter: chat-completion params + locate formats."""

    def __init__(
        self,
        family: str,
        build_chat_completion_params: Optional[Callable] = None,
        unsupported_user_config: Optional[List[str]] = None,
        use_reasoning_as_content_fallback: bool = False,
        reasoning_content_keys: Optional[List[str]] = None,
        locate_element_format: Optional[Dict[str, Any]] = None,
        image_pad_block_size: Optional[int] = None,
        supported_protocols: Optional[List[str]] = None,
        build_responses_params: Optional[Callable] = None,
        responses_unsupported_user_config: Optional[List[str]] = None,
        search_area_locate_format: Optional[Dict[str, Any]] = None,
        search_area_protocol: Optional[Dict[str, Any]] = None,
        element_protocol: Optional[Dict[str, Any]] = None,
        allowed_task_types: Optional[List[str]] = None,
        replanning_cycle_limit: Optional[int] = None,
        cache_enabled: bool = True,
        planning_kind: str = "standard",
        planning_plan_fn: Optional[Callable] = None,
        locate_kind: str = "standard",
        locate_fn: Optional[Callable] = None,
        locate_prompt_order: Optional[str] = None,
        replay_raw_assistant_message: bool = False,
        supports_action_deep_locate: Optional[bool] = None,
        insight_boolean_fn: Optional[Callable] = None,
        json_parser: Optional[Callable] = None,
    ):
        self.family = family
        self._build_params = build_chat_completion_params or _build_default_params
        self.unsupported_user_config = unsupported_user_config or []
        self.use_reasoning_as_content_fallback = use_reasoning_as_content_fallback
        self.reasoning_content_keys = reasoning_content_keys or ["reasoning_content"]
        self._locate_element_format = locate_element_format or DEFAULT_LOCATE_FORMAT
        self.image_pad_block_size = image_pad_block_size
        self.supported_protocols_list = supported_protocols or ["openai-chat"]
        self.build_responses_params = build_responses_params
        self.responses_unsupported_user_config = responses_unsupported_user_config or []
        self._search_area_locate_format = search_area_locate_format
        self._search_area_protocol = search_area_protocol
        self._element_protocol = element_protocol
        self.allowed_task_types = allowed_task_types  # None = all
        self.replanning_cycle_limit = replanning_cycle_limit
        self.cache_enabled = cache_enabled
        self.planning_kind = planning_kind
        self.planning_plan_fn = planning_plan_fn
        self.locate_kind = locate_kind
        self.locate_fn = locate_fn
        self._locate_prompt_order_source = locate_prompt_order
        self._locate_prompt_order: Optional[Dict[str, Any]] = None
        self.replay_raw_assistant_message = replay_raw_assistant_message
        self.supports_action_deep_locate = (
            supports_action_deep_locate
            if supports_action_deep_locate is not None
            else planning_kind == "standard"
        )
        self.insight_boolean_fn = insight_boolean_fn
        self.json_parser = json_parser
        self._locate_codec: Optional[Any] = None
        self._locate_protocol: Optional[Any] = None
        self._planning_protocol: Optional[Any] = None

    def supports_protocol(self, protocol: str) -> bool:
        return protocol in self.supported_protocols_list

    def build_chat_completion_params(
        self,
        midscene_defaults: Dict[str, Any],
        user_config: ModelRequestUserConfig,
        expected_json_object_response: bool = False,
    ) -> Dict[str, Any]:
        merged_user_config = dict(user_config)
        for key in self.unsupported_user_config:
            merged_user_config.pop(key, None)
        config = self._build_params(
            midscene_defaults, merged_user_config, expected_json_object_response
        )
        if merged_user_config.get("temperature") == "unset":
            config.pop("temperature", None)
        return config

    @property
    def locate_protocol(self):
        """Standard locate protocols: element + search-area (lazy import)."""
        if self._locate_protocol is None:
            from midscene.core.ai_model.model_adapter.default_locate_protocol import (
                create_default_element_protocol,
                create_default_search_area_protocol,
            )

            self._locate_protocol = {
                "element": self._element_protocol
                or create_default_element_protocol(self.json_parser),
                "search_area": self._search_area_protocol
                or create_default_search_area_protocol(self.json_parser),
            }
        return self._locate_protocol

    @property
    def planning_protocol(self):
        """Standard Midscene XML planning protocol (lazy import)."""
        if self._planning_protocol is None:
            from midscene.core.ai_model.model_adapter.default_planning_protocol import create_default_planning_protocol

            self._planning_protocol = create_default_planning_protocol()
        return self._planning_protocol

    @property
    def locate_result_codec(self):
        if self._locate_codec is None:
            self._locate_codec = create_locate_result_codec(
                self._locate_element_format
            )
        return self._locate_codec

    @property
    def locate_prompt_order(self) -> Dict[str, Any]:
        """Parsed locate prompt ordering (adapter-definition level)."""
        if self._locate_prompt_order is None:
            from midscene.core.ai_model.model_adapter.locate_prompt_order import (
                DEFAULT_LOCATE_PROMPT_ORDER,
                parse_locate_prompt_order,
            )

            self._locate_prompt_order = parse_locate_prompt_order(
                self._locate_prompt_order_source or DEFAULT_LOCATE_PROMPT_ORDER
            )
        return self._locate_prompt_order

    @property
    def search_area_result_codec(self):
        if self._search_area_locate_format is None:
            return self.locate_result_codec
        return create_locate_result_codec(self._search_area_locate_format)


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
        use_reasoning_as_content_fallback=True,
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


class ModelRuntime:
    """A model config bound to its family adapter (upstream ModelRuntime)."""

    def __init__(self, config: Dict[str, Any], adapter: Optional[ModelAdapter] = None):
        self.config = config
        self.adapter = adapter or get_model_adapter(config.get("modelFamily"))
        self.on_usage = None  # optional callback(AIUsageInfo)
        self.model_fallback: Optional[Dict[str, Any]] = None
        self._execution_id: Optional[str] = None

    @property
    def execution_id(self) -> str:
        """Stable per-runtime call id sent as `x-midscene-execution-id`."""
        if self._execution_id is None:
            self._execution_id = f"unscoped-{uuid.uuid4().hex}"
        return self._execution_id

    @property
    def model_family(self) -> Optional[str]:
        return self.config.get("modelFamily")

    @property
    def model_name(self) -> Optional[str]:
        return self.config.get("modelName")


def get_model_runtime(config: Dict[str, Any]) -> ModelRuntime:
    return ModelRuntime(
        config=config, adapter=get_model_adapter(config.get("modelFamily"))
    )


__all__ = [
    "ModelAdapter",
    "ModelRuntime",
    "get_model_adapter",
    "get_model_runtime",
    "is_locate_intent",
]
