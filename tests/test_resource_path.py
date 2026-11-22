"""Synced from upstream ``packages/android/tests/unit-test/resource-path.test.ts``."""

from midscene.android.resource_path import resolve_external_resource_path


def test_uses_the_unpacked_sibling_when_it_exists():
    """uses the unpacked sibling when it exists"""
    resource_path = (
        "/Applications/Midscene Studio.app/Contents/Resources/app.asar/"
        "node_modules/@midscene/android/bin/yadb"
    )
    unpacked_path = resource_path.replace(".asar/", ".asar.unpacked/")

    assert (
        resolve_external_resource_path(
            resource_path, lambda path: path == unpacked_path
        )
        == unpacked_path
    )


def test_uses_the_unpacked_windows_sibling_when_it_exists():
    """uses the unpacked Windows sibling when it exists"""
    resource_path = (
        r"C:\Program Files\Midscene Studio\resources\app.asar"
        r"\node_modules\@midscene\android\bin\yadb"
    )
    unpacked_path = (
        r"C:\Program Files\Midscene Studio\resources\app.asar.unpacked"
        r"\node_modules\@midscene\android\bin\yadb"
    )

    assert (
        resolve_external_resource_path(
            resource_path, lambda path: path == unpacked_path
        )
        == unpacked_path
    )


def test_keeps_the_original_path_when_no_unpacked_sibling_exists():
    """keeps the original path when no unpacked sibling exists"""
    resource_path = "/tmp/app.asar/node_modules/@midscene/android/bin/yadb"

    assert (
        resolve_external_resource_path(resource_path, lambda _path: False)
        == resource_path
    )


def test_keeps_ordinary_node_paths_unchanged():
    """keeps ordinary Node paths unchanged"""
    resource_path = "/workspace/node_modules/@midscene/android/bin/yadb"

    assert resolve_external_resource_path(resource_path) == resource_path
