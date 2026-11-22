"""Custom planning framework + UI-TARS / Auto-GLM planners.

Synced from upstream packages/core/src/ai-model:
  workflows/planning/custom-planning.ts
  models/ui-tars/{parser,actions,prompt,planning}.ts
  models/auto-glm/{parser,actions,prompt,planning,locate}.ts
  model-adapter/custom-planning-action.ts

AutoGLM prompts derive from Open-AutoGLM (zai-org, Apache-2.0).
"""

import json
from typing import Any, Callable, Dict, List, Optional

from midscene.core.ai_model.models.auto_glm.actions import transform_auto_glm_action
from midscene.core.ai_model.models.auto_glm.locate import auto_glm_locate
from midscene.core.ai_model.models.auto_glm.parser import (
    parse_auto_glm_planning_action,
    parse_auto_glm_planning_response,
    parse_auto_glm_response,
)
from midscene.core.ai_model.models.auto_glm.planning import create_auto_glm_planner
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.models.ui_tars.actions import (
    _transform_hotkey_input,
    transform_ui_tars_actions,
)
from midscene.core.ai_model.models.ui_tars.parser import (
    parse_ui_tars_action_calls,
    parse_ui_tars_planning_response,
)
from midscene.core.ai_model.models.ui_tars.planning import create_ui_tars_planner
from midscene.core.ai_model.model_adapter.custom_planning_action import (
    _normalize_custom_locate_fields,
    get_tap_located_pixel_result,
    normalize_custom_locate_fields,
)
from midscene.core.ai_model.model_adapter.planning import (
    resolve_custom_planning_definition,
)
from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.model_adapter.image_preprocess import (
    prepare_model_image,
)
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
)


# ---------------------------------------------------------------------------
# Custom planning framework (custom-planning.ts)
# ---------------------------------------------------------------------------

async def run_custom_planning(
    user_instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: Any,
    config: Dict[str, Any],
    include_locate_in_planning: bool = False,
    action_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one custom-planner turn (system prompt + screenshot + history)."""
    messages_config = config["messages"]
    system_prompt = messages_config["build_system_prompt"]()
    if action_context:
        system_prompt = f"{system_prompt}{action_context}\n"
    user_instruction_text = messages_config.get("build_user_instruction", lambda t: t)(
        user_instruction
    )

    adapter = model_runtime.adapter
    screenshot_base64 = ensure_data_url(get_screenshot_base64(context))
    shot_size = get_shot_size(context)
    prepared_image = prepare_model_image(
        image_base64=screenshot_base64,
        width=shot_size["width"],
        height=shot_size["height"],
        policy=(
            {"padBlockSize": adapter.image_pad_block_size}
            if adapter.image_pad_block_size
            else None
        ),
    )

    history_image_limit = messages_config.get("history_image_limit")
    if conversation_history.pending_feedback_message:
        conversation_history.append_message(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{conversation_history.pending_feedback_message}. The "
                            "previous action has been executed, here is the latest "
                            "screenshot. Please continue according to the instruction."
                        ),
                    }
                ],
            }
        )
        conversation_history.reset_pending_feedback_message_if_exists()

    conversation_history.append_message(
        {"role": "user", "content": [{"type": "image", "url": prepared_image["image_base64"]}]}
    )

    if messages_config["system_prompt_placement"] == "system-message":
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "text", "text": user_instruction_text}]},
        ]
        messages.extend(
            conversation_history.snapshot(history_image_limit)
        )
    else:
        messages = [
            {"role": "user", "content": f"{system_prompt}{user_instruction_text}"},
            *conversation_history.snapshot(history_image_limit),
        ]

    response = await call_ai_with_string_response(
        messages, model_runtime, {"requiresOriginalImageDetail": include_locate_in_planning}
    )
    content = response["content"]
    usage = response.get("usage")

    try:
        parsed = config["parse_response"](content, context, model_runtime)
        actions = config["transform_actions"](
            parsed, context, action_space, model_runtime
        )
        normalize_custom_locate_fields(
            actions,
            config["coordinates"],
            {
                "preparedSize": prepared_image["prepared_size"],
                "contentSize": prepared_image["content_size"],
            },
        )
        should_continue = config["should_continue_planning"](parsed, actions)
    except AIResponseParseError:
        raise
    except Exception as parse_error:
        raise AIResponseParseError(
            f"Parse error: {parse_error}",
            json.dumps(content, ensure_ascii=False, indent=2) if not isinstance(content, str) else content,
            usage,
        ) from parse_error

    assistant_content = messages_config.get("build_assistant_content", lambda p, c: None)(
        parsed, content
    )
    if assistant_content:
        conversation_history.append_message(
            {"role": "assistant", "content": assistant_content}
        )

    return {
        "actions": actions,
        "log": config["build_response_log"](parsed, content),
        "usage": usage,
        "should_continue_planning": should_continue,
        "raw_response": content,
    }


# ---------------------------------------------------------------------------
# Adapter wiring: bind custom plan/locate functions to their adapters
# ---------------------------------------------------------------------------

def register_custom_planners() -> None:
    """Attach the custom planning/locate callables to their model adapters."""
    from midscene.core.ai_model.models.registry import get_model_adapter

    auto_glm = get_model_adapter("auto-glm")
    auto_glm.planning_plan_fn = _make_auto_glm_plan_fn(False)
    auto_glm.locate_fn = auto_glm_locate

    auto_glm_multilingual = get_model_adapter("auto-glm-multilingual")
    auto_glm_multilingual.planning_plan_fn = _make_auto_glm_plan_fn(True)
    auto_glm_multilingual.locate_fn = auto_glm_locate

    for family in ("vlm-ui-tars", "vlm-ui-tars-doubao", "vlm-ui-tars-doubao-1.5"):
        adapter = get_model_adapter(family)
        adapter.planning_plan_fn = _make_ui_tars_plan_fn()


def _make_auto_glm_plan_fn(is_multilingual: bool) -> Callable:
    async def plan(
        instruction: str,
        context: Any,
        model_runtime: ModelRuntime,
        action_space: List[Any],
        conversation_history: Any,
        include_locate_in_planning: bool = False,
        action_context: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        result = await run_custom_planning(
            instruction,
            context,
            model_runtime,
            action_space,
            conversation_history,
            resolve_custom_planning_definition(
                create_auto_glm_planner(is_multilingual)
            ),
            include_locate_in_planning,
            action_context,
        )
        result["yaml_flow"] = _yaml_flow_of(result["actions"])
        return result

    return plan


def _make_ui_tars_plan_fn() -> Callable:
    async def plan(
        instruction: str,
        context: Any,
        model_runtime: ModelRuntime,
        action_space: List[Any],
        conversation_history: Any,
        include_locate_in_planning: bool = False,
        action_context: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        result = await run_custom_planning(
            instruction,
            context,
            model_runtime,
            action_space,
            conversation_history,
            resolve_custom_planning_definition(create_ui_tars_planner()),
            include_locate_in_planning,
            action_context,
        )
        result["yaml_flow"] = _yaml_flow_of(result["actions"])
        return result

    return plan


def _yaml_flow_of(actions: List[Dict[str, Any]]) -> str:
    import yaml

    flow = [
        {"type": action["type"], **(action.get("param") or {})} for action in actions
    ]
    return yaml.dump(
        {"tasks": [{"name": "flow", "flow": flow}]},
        allow_unicode=True,
        sort_keys=False,
        width=10**6,
    ).strip()


__all__ = [
    "_normalize_custom_locate_fields",
    "_transform_hotkey_input",
    "auto_glm_locate",
    "create_auto_glm_planner",
    "create_ui_tars_planner",
    "get_tap_located_pixel_result",
    "normalize_custom_locate_fields",
    "parse_auto_glm_planning_action",
    "parse_auto_glm_planning_response",
    "parse_auto_glm_response",
    "parse_ui_tars_action_calls",
    "parse_ui_tars_planning_response",
    "register_custom_planners",
    "run_custom_planning",
    "transform_auto_glm_action",
    "transform_ui_tars_actions",
]
