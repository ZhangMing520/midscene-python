"""Connectivity test (upstream ai-model/connectivity)."""

from midscene.core.ai_model.connectivity.fixture import (
    CONNECTIVITY_FIXTURE_SHOT_SIZE,
    connectivity_fixture_image,
)
from midscene.core.ai_model.connectivity.run_connectivity_test import run_connectivity_test

__all__ = [
    "CONNECTIVITY_FIXTURE_SHOT_SIZE",
    "connectivity_fixture_image",
    "run_connectivity_test",
]
