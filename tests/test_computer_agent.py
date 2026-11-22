"""Port of upstream packages/computer/tests/unit-test/agent.test.ts.

Only the ``should create agent instance`` case was covered by the former
aggregate ``tests/test_computer.py``; the option/custom-action cases and the
Node-only ``agentFromComputer`` alias are not part of the Python API.
"""

from midscene.computer import ComputerAgent
from midscene.computer.device import ComputerDevice


def test_should_create_agent_instance():
    """should create agent instance."""

    device = ComputerDevice()
    agent = ComputerAgent(device)

    assert agent is not None
    assert agent.interface is device
    assert agent.interface_type.value == "computer"
