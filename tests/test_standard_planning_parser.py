"""Synced from upstream packages/core/tests/unit-test/standard-planning-parser.test.ts."""

from midscene.core.ai_model.workflows.planning.standard_planning_parser import (
    parse_xml_planning_response,
)


def test_extracts_the_continuous_content_between_the_protocol_boundary_tags():
    """extracts the continuous content between the protocol boundary tags"""
    xml = (
        "<planning>Choose the next action</planning>\n"
        "<action-type>Tap</action-type>\n"
        '<action-param-json>{"locate":{"prompt":"Submit"}}</action-param-json>\n'
        "<memory>Keep this outside the action output</memory>"
    )

    _parsed, raw_action_output = parse_xml_planning_response(
        xml,
        ("action-type", "action-param-json"),
        include_thought=True,
    )

    assert raw_action_output == (
        "<action-type>Tap</action-type>\n"
        '<action-param-json>{"locate":{"prompt":"Submit"}}</action-param-json>'
    )
