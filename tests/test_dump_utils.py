"""Synced from upstream packages/core/tests/unit-test/dump-utils.test.ts."""

from midscene.core.utils import (
    anti_escape_script_tag,
    escape_script_tag,
    insert_content_before_closing_html,
    report_html_content,
)


def test_should_escape_and_unescape_content_correctly():
    original = "<script>alert(1)</script>"

    escaped = escape_script_tag(original)

    assert "<" not in escaped
    assert ">" not in escaped
    assert anti_escape_script_tag(escaped) == original


def test_should_generate_dump_script_tag_without_attributes():
    html = "<html><body></body></html>"
    assert insert_content_before_closing_html(html, "X").endswith("X\n</html>")

    content = report_html_content('{"a": 1}', with_tpl=False)
    assert 'type="midscene_web_dump"' in content
    assert '"a": 1' in content
