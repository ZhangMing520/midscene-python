"""Jev planning action builder (upstream models/jev/planning-action.ts)."""

import json
from typing import Any

from midscene.core.ai_model.models.jev.locate import (
    map_jev_box,
)
from midscene.core.ai_model.service_caller.system_one import SystemOneError


def build_jev_action(
    decision: dict[str, Any],
    jev_context: dict[str, Any],
    instruction: str,
    action_space: list[Any],
    include_locate_in_planning: bool,
    shot_size: dict[str, Any],
    reference_images: list[str] | None = None,
) -> list[dict[str, Any]]:
    choice = decision["choice"]
    if choice["kind"] == "complete":
        return []
    if choice["kind"] != "action":
        raise SystemOneError("Delegated actions must use the default planner")
    action = choice["action"]
    fields = list(action.locate_fields)
    located_pixel_result = None
    if include_locate_in_planning and len(fields) == 1:
        if not decision.get("target") or decision["target"].get("type") != "box":
            raise SystemOneError("Missing Jev planning target box")
        located_pixel_result = map_jev_box(decision["target"]["box"], shot_size)

    locate_prompt = (
        "Locate the target for parameter {field} of action "
        "{action} ({description}) for the NEXT step toward this goal. Use the "
        "current screenshot as authoritative and consider execution feedback. "
        "Task context: {context}"
    )

    def locate_param(field: str) -> dict[str, Any]:
        prompt = locate_prompt.format(
            field=json.dumps(field),
            action=json.dumps(action.name),
            description=action.description or action.name,
            context=json.dumps(jev_context["state"]),
        )
        return {
            "prompt": (
                {"prompt": prompt, "images": [{"url": url} for url in reference_images]}
                if reference_images
                else prompt
            ),
            **(
                {"locatedPixelResult": located_pixel_result}
                if located_pixel_result
                else {}
            ),
        }

    param = {field: locate_param(field) for field in fields}
    return [{"type": action.name, "param": param}]
