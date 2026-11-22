"""Synced from upstream packages/core/tests/unit-test/xml-parser.test.ts."""

from midscene.core.ai_model.shared.xml import extract_xml_tag


def test_should_extract_simple_tag_content():
    assert extract_xml_tag("<log>hello</log>", "log") == "hello"


def test_should_handle_case_insensitive_tag_matching():
    assert extract_xml_tag("<LOG>hello</LOG>", "log") == "hello"


def test_should_extract_last_occurrence_when_multiple_tags_exist():
    content = "<log>first</log>middle<log>second</log>"
    assert extract_xml_tag(content, "log") == "second"


def test_should_extract_content_from_half_open_tag_when_closing_tag_is_missing():
    assert extract_xml_tag("<action-type>Input", "action-type") == "Input"


def test_should_extract_content_after_think_tag_when_model_prepends_thinking():
    content = "<think>let me think</think><planning>real plan</planning>"
    assert extract_xml_tag(content, "planning") == "real plan"
