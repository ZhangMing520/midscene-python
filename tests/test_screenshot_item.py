"""Synced from upstream packages/core/tests/unit-test/screenshot-item.test.ts
and dump-utils.test.ts (screenshot restoration)."""

from midscene.core.screenshot_item import (
    ScreenshotItem,
    extract_image_by_id_sync,
    normalize_screenshot_ref,
)


def test_should_create_screenshot_item_and_serialize_screenshot_ref_fields(tmp_path):
    item = ScreenshotItem.create("data:image/jpeg;base64,AAA", 123)
    assert item.format == "jpeg"
    assert item.extension == "jpeg"
    assert item.raw_base64 == "AAA"

    ref = item.to_serializable()
    assert ref["type"] == "midscene_screenshot_ref"
    assert ScreenshotItem.is_serialized(ref)
    assert normalize_screenshot_ref(ref) == ref
    assert normalize_screenshot_ref({"type": "nope"}) is None

    html = tmp_path / "report.html"
    html.write_text(
        '<script type="midscene-image" data-id="abc">'
        "__midscene_lt__svg__midscene_gt__"
        "</script>",
        encoding="utf-8",
    )
    assert extract_image_by_id_sync(str(html), "abc") == "<svg>"


def test_should_restore_screenshot_references_via_lazy_getter(tmp_path):
    persisted = ScreenshotItem.create("data:image/png;base64,AAA", 1)
    persisted_id = persisted.id
    inline_path = tmp_path / "inline.html"
    inline_path.write_text(
        f'<script type="midscene-image" data-id="{persisted_id}">'
        "data:image/png;base64,BBB"
        "</script>",
        encoding="utf-8",
    )
    persisted.mark_persisted_inline(str(inline_path))

    assert persisted.has_base64() is False
    assert persisted.base64 == "data:image/png;base64,BBB"
