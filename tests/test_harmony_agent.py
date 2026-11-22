"""Port of upstream packages/harmony/tests/unit-test/agent.test.ts.

Only the agent-construction case was covered by the former aggregate
``tests/test_harmony.py``. The Node-only ``agentFromHdcDevice`` uses an HDC
device wrapper and environment overrides that the Python agent does not
expose.
"""

from midscene.harmony.agent import HarmonyAgent
from midscene.harmony.device import HarmonyDevice


def test_should_create_harmony_agent_successfully():
    """should create HarmonyAgent successfully."""

    device = HarmonyDevice()
    agent = HarmonyAgent(device)

    assert agent is not None
    assert agent.interface is device
    assert agent.interface_type.value == "harmony"
