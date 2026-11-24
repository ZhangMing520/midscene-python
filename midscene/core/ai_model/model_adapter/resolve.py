"""Resolved model adapter (upstream ai-model/model-adapter/resolve.ts)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from midscene.core.ai_model.model_adapter.chat_completion import (
    resolve_chat_completion,
)
from midscene.core.ai_model.model_adapter.responses import resolve_responses
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)
from midscene.core.ai_model.models.default import (
    DEFAULT_LOCATE_FORMAT,
    _build_default_params,
)
from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_codec,
)


@dataclass
class ResolvedModelAdapter:
    """Runtime view of a resolved adapter definition.

    Field names mirror upstream ``ResolvedModelAdapter`` (lower snake_case).
    The Python runtime keeps its richer :class:`ModelAdapter`; this dataclass
    exists so callers can construct the upstream-shaped adapter view from an
    adapter definition dict.
    """

    model_type: str = "generative"
    allowed_task_types: list[str] | None = None
    supported_protocols: list[str] = field(default_factory=lambda: ["openai-chat"])
    json_parser: Callable[..., Any] | None = None
    chat_completion: dict[str, Any] = field(default_factory=dict)
    resolve_image_detail: Callable[..., Any] | None = None
    responses: dict[str, Any] = field(default_factory=dict)
    build_codex_app_server_params: Callable[..., Any] | None = None
    image_preprocess: dict[str, Any] = field(default_factory=dict)
    insight: dict[str, Any] = field(default_factory=dict)
    planning: dict[str, Any] = field(default_factory=dict)
    locate: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls, config: dict[str, Any] | None = None, model_family: str = "default"
    ) -> "ResolvedModelAdapter":
        config = config or {}
        return cls(
            model_type=config.get("model_type", "generative"),
            allowed_task_types=config.get("allowed_task_types"),
            supported_protocols=(
                config["supported_protocols"]
                if "supported_protocols" in config
                else ["openai-chat"]
            ),
            json_parser=config.get("json_parser"),
            chat_completion=resolve_chat_completion(config.get("chat_completion")),
            resolve_image_detail=config.get("resolve_image_detail"),
            responses=resolve_responses(config.get("responses")),
            build_codex_app_server_params=config.get("build_codex_app_server_params"),
            image_preprocess=config.get("image_preprocess") or {},
            insight=config.get("insight") or {},
            planning=config.get("planning") or {},
            locate=config.get("locate") or {},
        )


class ModelAdapter:
    """Resolved per-family adapter: chat-completion params + locate formats."""

    def __init__(
        self,
        family: str,
        build_chat_completion_params: Callable | None = None,
        unsupported_user_config: list[str] | None = None,
        use_reasoning_as_content_fallback: bool = False,
        reasoning_content_keys: list[str] | None = None,
        locate_element_format: dict[str, Any] | None = None,
        image_pad_block_size: int | None = None,
        supported_protocols: list[str] | None = None,
        build_responses_params: Callable | None = None,
        responses_unsupported_user_config: list[str] | None = None,
        search_area_locate_format: dict[str, Any] | None = None,
        search_area_protocol: dict[str, Any] | None = None,
        element_protocol: dict[str, Any] | None = None,
        allowed_task_types: list[str] | None = None,
        replanning_cycle_limit: int | None = None,
        cache_enabled: bool = True,
        planning_kind: str = "standard",
        planning_plan_fn: Callable | None = None,
        locate_kind: str = "standard",
        locate_fn: Callable | None = None,
        locate_prompt_order: str | None = None,
        replay_raw_assistant_message: bool = False,
        supports_action_deep_locate: bool | None = None,
        insight_boolean_fn: Callable | None = None,
        json_parser: Callable | None = None,
        extract_content_and_reasoning: Callable | None = None,
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
        self._locate_prompt_order: dict[str, Any] | None = None
        self.replay_raw_assistant_message = replay_raw_assistant_message
        self.supports_action_deep_locate = (
            supports_action_deep_locate
            if supports_action_deep_locate is not None
            else planning_kind == "standard"
        )
        self.insight_boolean_fn = insight_boolean_fn
        self.json_parser = json_parser
        self.extract_content_and_reasoning = extract_content_and_reasoning
        self._locate_codec: Any | None = None
        self._locate_protocol: Any | None = None
        self._planning_protocol: Any | None = None

    def supports_protocol(self, protocol: str) -> bool:
        return protocol in self.supported_protocols_list

    def build_chat_completion_params(
        self,
        midscene_defaults: dict[str, Any],
        user_config: ModelRequestUserConfig,
        expected_json_object_response: bool = False,
    ) -> dict[str, Any]:
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
            from midscene.core.ai_model.model_adapter.locate import resolve_locate

            locate_adapter = resolve_locate(self)
            self._locate_protocol = {
                "element": locate_adapter["element"]["protocol"],
                "search_area": locate_adapter["search_area"]["protocol"],
            }
        return self._locate_protocol

    @property
    def planning_protocol(self):
        """Standard Midscene XML planning protocol (lazy import)."""
        if self._planning_protocol is None:
            from midscene.core.ai_model.model_adapter.default_planning_protocol import (
                create_default_planning_protocol,
            )

            self._planning_protocol = create_default_planning_protocol()
        return self._planning_protocol

    @property
    def locate_result_codec(self):
        if self._locate_codec is None:
            self._locate_codec = create_locate_result_codec(self._locate_element_format)
        return self._locate_codec

    @property
    def locate_prompt_order(self) -> dict[str, Any]:
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


__all__ = ["ModelAdapter", "ResolvedModelAdapter"]
