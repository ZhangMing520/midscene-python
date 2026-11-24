"""CLI-only bridge between an Agent runtime and observation artifacts.

Port of upstream agent-tools/observation-artifact.ts. The TypeScript runtime
uses a symbol-keyed capability; Python exposes the same adapter through a
well-known attribute name.
"""

from typing import Any

from midscene.shared.agent_tools.types import UIObservationRecord

OBSERVATION_ARTIFACT_ADAPTER_ATTR = "observation_artifact_adapter"

# @internal Property name used by Core and the CLI artifact commands.
observation_artifact_adapter_symbol = OBSERVATION_ARTIFACT_ADAPTER_ATTR


def resolve_observation_artifact_adapter(agent: Any) -> Any | None:
    """Read the CLI artifact capability attached by the Core Agent."""
    return getattr(agent, OBSERVATION_ARTIFACT_ADAPTER_ATTR, None)


class ObservationArtifactAdapter:
    """Protocol for exporting and loading observation artifacts."""

    async def export_record(self, observation: Any) -> UIObservationRecord:
        raise NotImplementedError

    def load_record(self, record: UIObservationRecord) -> Any:
        raise NotImplementedError


__all__ = [
    "OBSERVATION_ARTIFACT_ADAPTER_ATTR",
    "ObservationArtifactAdapter",
    "observation_artifact_adapter_symbol",
    "resolve_observation_artifact_adapter",
]
