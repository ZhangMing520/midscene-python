"""Locate model-family configuration error messages.

Synced from upstream packages/core/src/ai-model/shared/model-locate-result/errors.ts.
"""

from midscene.shared.env.constants import MODEL_CONFIG_DOC_URL


def model_family_required_for_locate_message(slot: str | None = None) -> str:
    role = "Locate" if slot == "locate" else "Default"
    config_key = (
        "MIDSCENE_LOCATE_MODEL_FAMILY" if slot == "locate" else "MIDSCENE_MODEL_FAMILY"
    )
    return (
        f"{role} model family is required for locate. Configure {config_key} so "
        f"Midscene can parse locate coordinates correctly. {MODEL_CONFIG_DOC_URL}"
    )


def planning_model_family_required_for_locate_message(
    slot: str | None = None,
) -> str:
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


__all__ = [
    "model_family_required_for_locate_message",
    "planning_model_family_required_for_locate_message",
]
