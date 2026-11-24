"""Screenshot references for verbose CLI output.

Port of upstream cli/verbose-screenshot.ts.
"""

import json
import os
from pathlib import Path
from typing import Any, TypeGuard, cast

from midscene.shared.cli.screenshot_file import write_cli_screenshot_file


def _is_record(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _is_screenshot_ref(value: Any) -> TypeGuard[dict[str, Any]]:
    return _is_record(value) and value.get("type") == "midscene_screenshot_ref"


def _to_serializable_screenshot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None

    to_serializable = getattr(value, "to_serializable", None)
    if callable(to_serializable):
        try:
            serialized = to_serializable()
            return serialized if _is_screenshot_ref(serialized) else None
        except Exception:  # noqa: BLE001
            return None

    return value if _is_screenshot_ref(value) else None


def _get_string_property(value: Any, key: str) -> str | None:
    if not _is_record(value):
        return None
    try:
        property_value = value.get(key)
        return (
            property_value
            if isinstance(property_value, str) and property_value
            else None
        )
    except Exception:  # noqa: BLE001
        return None


def _screenshot_raw_base64(value: Any) -> str | None:
    raw_base64 = _get_string_property(value, "rawBase64")
    if raw_base64:
        return raw_base64

    base64_value = _get_string_property(value, "base64")
    if not base64_value:
        return None
    import re

    match = re.match(r"^data:image/(?:png|jpeg|jpg);base64,(.+)$", base64_value)
    return match.group(1) if match else None


def _inline_screenshot_cache_key(
    raw_base64: str,
    serialized: dict[str, Any],
    directory_path: str | None,
    directory_name: str | None,
    extension: str | None,
) -> str:
    return json.dumps(
        [
            serialized.get("id"),
            serialized.get("mimeType"),
            directory_path,
            directory_name,
            extension,
            raw_base64,
        ],
        ensure_ascii=False,
    )


def _export_inline_screenshot_for_verbose(
    value: Any,
    serialized: dict[str, Any],
    options: dict[str, Any],
) -> str | None:
    existing_path = serialized.get("path")
    if isinstance(existing_path, str):
        return existing_path

    export_mode = options.get("exportMode") or "tmp"
    if export_mode == "none":
        return None

    raw_base64 = _screenshot_raw_base64(value)
    if not raw_base64:
        return None

    report_file = options.get("reportFile")
    directory_path = (
        str(Path(report_file).parent / "screenshots")
        if export_mode == "report" and isinstance(report_file, str) and report_file
        else None
    )
    directory_name = None if directory_path else "midscene-cli-screenshots"
    extension = _get_string_property(value, "extension")
    cache_key = _inline_screenshot_cache_key(
        raw_base64, serialized, directory_path, directory_name, extension
    )
    cache = options.get("cache")
    if cache is not None:
        # The CLI context supplies a string-to-path cache for deduplication.
        path_cache = cast(dict[str, str], cache)
        cached_path = path_cache.get(cache_key)
        if cached_path:
            return cached_path

    try:
        path = write_cli_screenshot_file(
            raw_base64,
            {
                "id": serialized.get("id"),
                "mimeType": serialized.get("mimeType"),
                "extension": extension,
                **(
                    {"directoryPath": directory_path}
                    if directory_path
                    else {"directoryName": directory_name}
                ),
                "overwrite": False,
            },
        )
        if cache is not None:
            path_cache[cache_key] = path
        return path
    except Exception:  # noqa: BLE001
        return None


def collect_screenshot_refs(
    value: Any, options: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    options = options or {}
    screenshots: list[dict[str, Any]] = []

    def visit(candidate: Any, timing: Any = None) -> None:
        if isinstance(candidate, list):
            for item in candidate:
                visit(item, timing)
            return

        serialized = _to_serializable_screenshot(candidate)
        if serialized is not None and _is_screenshot_ref(serialized):
            screenshot: dict[str, Any] = {
                "id": serialized.get("id"),
                "storage": serialized.get("storage"),
            }
            exported_path = _export_inline_screenshot_for_verbose(
                candidate, serialized, options
            )
            if exported_path:
                screenshot["path"] = exported_path
                screenshot["file"] = Path(exported_path).name
            if isinstance(timing, str):
                screenshot["timing"] = timing
            screenshots.append(screenshot)
            return

        if not _is_record(candidate):
            return

        screenshot_record = candidate.get("screenshot")
        if screenshot_record:
            visit(screenshot_record, candidate.get("timing"))
        if candidate.get("recorder"):
            visit(candidate.get("recorder"))
        ui_context = candidate.get("uiContext")
        if _is_record(ui_context):
            visit(ui_context.get("screenshot"))

    visit(value)
    return screenshots


def path_for_report_screenshot(path: str, report_file: Any = None) -> str:
    resolved_path = (
        str(Path(report_file).parent / path)
        if isinstance(report_file, str)
        and report_file
        and (path.startswith("./") or path.startswith("../"))
        else path
    )

    if not os.path.isabs(resolved_path):
        return resolved_path

    try:
        relative_path = os.path.relpath(resolved_path, os.getcwd())
    except ValueError:
        return resolved_path
    if (
        relative_path
        and not relative_path.startswith("..")
        and not os.path.isabs(relative_path)
    ):
        return relative_path
    return resolved_path


def latest_screenshot_path_for_ai_act(
    value: Any, options: dict[str, Any] | None = None
) -> str:
    options = dict(options or {})
    options.setdefault("exportMode", "report")
    screenshots = collect_screenshot_refs(value, options)
    path = ""
    for screenshot in reversed(screenshots):
        if isinstance(screenshot.get("path"), str) and screenshot["path"]:
            path = screenshot["path"]
            break
    return path_for_report_screenshot(path, options.get("reportFile")) if path else ""


def render_screenshot_list(screenshots: Any) -> str:
    if not isinstance(screenshots, list) or not screenshots:
        return ""
    rendered = []
    for item in screenshots:
        if not _is_record(item):
            continue
        path = (
            item.get("path")
            if isinstance(item.get("path"), str)
            else item.get("file")
            if isinstance(item.get("file"), str)
            else item.get("id")
            if isinstance(item.get("id"), str)
            else ""
        )
        timing = item.get("timing") if isinstance(item.get("timing"), str) else ""
        text = " ".join(part for part in (timing, path) if part)
        if text:
            rendered.append(text)
    return ", ".join(rendered)


__all__ = [
    "collect_screenshot_refs",
    "latest_screenshot_path_for_ai_act",
    "path_for_report_screenshot",
    "render_screenshot_list",
]
