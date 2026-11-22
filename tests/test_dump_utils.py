"""Synced from upstream packages/core/tests/unit-test/dump-utils.test.ts."""

import json

import pytest

from midscene.core.dump.screenshot_restoration import (
    create_inline_image_resolver,
    restore_image_references,
    restore_report_image_references,
)
from midscene.core.utils import (
    anti_escape_script_tag,
    escape_script_tag,
    insert_content_before_closing_html,
    report_html_content,
)

_IMAGE_MAP = {
    "img1": "data:image/png;base64,abc123",
    "img2": "data:image/png;base64,def456",
}
_RESOLVER = create_inline_image_resolver(_IMAGE_MAP)


def _screenshot_ref(image_id: str, captured_at: int = 1) -> dict:
    return {
        "type": "midscene_screenshot_ref",
        "id": image_id,
        "capturedAt": captured_at,
        "mimeType": "image/png",
        "storage": "inline",
    }


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


def test_should_restore_screenshot_references_to_lazy_base64():
    """should restore screenshot references to { base64 } format via lazy getter"""
    result = restore_image_references({"screenshot": _screenshot_ref("img1")}, _RESOLVER)
    assert result["screenshot"].base64 == "data:image/png;base64,abc123"


def test_should_restore_reference_image_url_refs_directly_to_strings():
    """should restore reference-image URL refs directly to strings"""
    data = {
        "image": {
            "url": {
                "type": "midscene_image_url_ref",
                "id": "img1",
                "mimeType": "image/png",
                "storage": "inline",
            }
        }
    }
    result = restore_image_references(data, _RESOLVER)
    assert result["image"]["url"] == "data:image/png;base64,abc123"


def test_should_use_the_same_resolver_for_both_stored_image_reference_types():
    """should use the same resolver for both stored image reference types"""
    resolved_types = []

    def resolver(ref):
        resolved_types.append(ref["type"])
        return _IMAGE_MAP[ref["id"]]

    result = restore_image_references(
        {
            "screenshot": _screenshot_ref("img1"),
            "imageUrl": {
                "type": "midscene_image_url_ref",
                "id": "img2",
                "mimeType": "image/png",
                "storage": "inline",
            },
        },
        resolver,
    )
    assert result["imageUrl"] == "data:image/png;base64,def456"
    assert result["screenshot"].base64 == "data:image/png;base64,abc123"
    assert resolved_types == [
        "midscene_image_url_ref",
        "midscene_screenshot_ref",
    ]


def test_should_throw_when_an_inline_report_image_is_missing():
    """should throw when an inline report image is missing"""
    missing_image_resolver = create_inline_image_resolver({})
    with pytest.raises(
        ValueError, match='Missing inline report image "missing-image"'
    ):
        missing_image_resolver(
            {
                "type": "midscene_image_url_ref",
                "id": "missing-image",
                "mimeType": "image/webp",
                "storage": "inline",
            }
        )


def test_should_restore_report_image_urls_from_serialized_paths_and_mime_types():
    """should restore report image URLs from serialized paths and MIME types"""
    data = {
        "screenshot": {
            "type": "midscene_screenshot_ref",
            "id": "shot-1",
            "capturedAt": 1,
            "mimeType": "image/png",
            "storage": "file",
            "path": "./custom/shot-1.png",
        },
        "referenceImage": {
            "type": "midscene_image_url_ref",
            "id": "reference-webp",
            "mimeType": "image/webp",
            "storage": "inline",
        },
    }

    restored = restore_report_image_references(
        data, "https://example.com/reports/run/"
    )

    assert (
        restored["screenshot"].base64
        == "https://example.com/reports/run/custom/shot-1.png"
    )
    assert (
        restored["referenceImage"]
        == "https://example.com/reports/run/screenshots/reference-webp.webp"
    )


def test_should_handle_nested_objects():
    """should handle nested objects"""
    data = {
        "level1": {
            "level2": {"screenshot": _screenshot_ref("img2")},
        }
    }
    result = restore_image_references(data, _RESOLVER)
    assert (
        result["level1"]["level2"]["screenshot"].base64
        == "data:image/png;base64,def456"
    )


def test_should_handle_arrays():
    """should handle arrays"""
    result = restore_image_references(
        [_screenshot_ref("img1"), _screenshot_ref("img2")], _RESOLVER
    )
    assert result[0].base64 == "data:image/png;base64,abc123"
    assert result[1].base64 == "data:image/png;base64,def456"


def test_should_throw_lazily_for_unknown_screenshot_ids():
    """should throw lazily for unknown screenshot IDs"""
    result = restore_image_references(
        {"screenshot": _screenshot_ref("uuid-not-in-map")}, _RESOLVER
    )
    with pytest.raises(
        ValueError, match='Missing inline report image "uuid-not-in-map"'
    ):
        _ = result["screenshot"].base64


def test_should_support_directory_path_fallback_via_resolver():
    """should support directory-path fallback via resolver"""
    directory_resolver = lambda ref: f"./screenshots/{ref['id']}.png"
    result = restore_image_references(
        {"screenshot": _screenshot_ref("uuid-abc-123")}, directory_resolver
    )
    assert result["screenshot"].base64 == "./screenshots/uuid-abc-123.png"


def test_should_preserve_captured_at_when_restoring_screenshot_references():
    """should preserve capturedAt when restoring screenshot references"""
    result = restore_image_references(
        {"screenshot": _screenshot_ref("img1", 1700000000123)}, _RESOLVER
    )
    assert result["screenshot"].base64 == "data:image/png;base64,abc123"
    assert result["screenshot"].captured_at == 1700000000123


def test_should_work_correctly_for_directory_mode_report_flow():
    """should work correctly for directory mode report flow"""
    directory_resolver = lambda ref: f"./screenshots/{ref['id']}.png"
    data = {
        "executions": [
            {
                "tasks": [
                    {"uiContext": {"screenshot": _screenshot_ref("abc-123-def")}}
                ]
            }
        ]
    }
    result = restore_image_references(data, directory_resolver)
    assert (
        result["executions"][0]["tasks"][0]["uiContext"]["screenshot"].base64
        == "./screenshots/abc-123-def.png"
    )


def test_should_handle_primitive_values():
    """should handle primitive values"""
    assert restore_image_references("string", _RESOLVER) == "string"
    assert restore_image_references(123, _RESOLVER) == 123
    assert restore_image_references(None, _RESOLVER) is None


def test_should_lazily_resolve_images_resolver_called_only_on_access():
    """should lazily resolve images (resolver called only on access)"""
    resolve_count = 0

    def counting_resolver(ref):
        nonlocal resolve_count
        resolve_count += 1
        return _IMAGE_MAP.get(ref["id"], "")

    result = restore_image_references(
        {"a": _screenshot_ref("img1"), "b": _screenshot_ref("img2")},
        counting_resolver,
    )
    assert resolve_count == 0

    _ = result["a"].base64
    assert resolve_count == 1

    _ = result["a"].base64
    assert resolve_count == 1

    _ = result["b"].base64
    assert resolve_count == 2


def test_should_produce_enumerable_base64_property_visible_to_json():
    """should produce enumerable base64 property (visible to JSON.stringify)"""
    result = restore_image_references(_screenshot_ref("img1"), _RESOLVER)
    restored = json.loads(json.dumps(result, default=lambda obj: obj.to_dict()))
    assert restored["base64"] == "data:image/png;base64,abc123"
