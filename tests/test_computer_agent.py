"""Port of upstream packages/computer/tests/unit-test/agent.test.ts.

Only the ``should create agent instance`` case was covered by the former
aggregate ``tests/test_computer.py``; the option/custom-action cases and the
Node-only ``agentFromComputer`` alias are not part of the Python API.
"""

import pytest

from midscene.computer import (
    ComputerAgent,
    agent_for_computer,
    agent_from_computer,
)
from midscene.computer.device import ComputerDevice
from midscene.core.agent.agent_options import AgentOptions


def test_should_create_agent_instance():
    """should create agent instance."""

    device = ComputerDevice()
    agent = ComputerAgent(device)

    assert agent is not None
    assert agent.interface is device
    assert agent.interface_type.value == "computer"


def test_should_create_agent_with_options():
    """should create agent with options."""

    device = ComputerDevice()
    agent = ComputerAgent(device, AgentOptions(ai_action_context="Test context"))

    assert agent is not None


@pytest.mark.skip(
    reason=(
        "ComputerDevice does not accept customActions; Python action spaces "
        "are built from the interface type"
    )
)
def test_should_create_agent_with_custom_actions():
    """should create agent with custom actions."""

    ComputerAgent(ComputerDevice())


def test_keeps_agentfromcomputer_as_backward_compatible_alias():
    """keeps agentFromComputer as backward-compatible alias of agentForComputer"""
    assert agent_from_computer is agent_for_computer
