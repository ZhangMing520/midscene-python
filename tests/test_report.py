"""Synced from upstream packages/core/tests/unit-test/report.test.ts."""

import json
from pathlib import Path

import pytest

from midscene.core.dump.html_utils import (
    extract_all_dump_scripts_sync,
    generate_dump_script_tag,
    generate_image_script_tag,
    get_report_tpl,
    parse_image_scripts,
)
from midscene.core.dump.report_artifact_reader import read_report_dump_scripts
from midscene.core.report import ReportMergingTool, is_directory_mode_report
from midscene.core.utils import get_version


def _write_report(directory, name: str, dump: dict, attributes: dict) -> str:
    path = Path(directory) / f"{name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        get_report_tpl()
        + "\n"
        + generate_dump_script_tag(json.dumps(dump), attributes),
        encoding="utf-8",
    )
    return str(path)


def generate_n_reports(
    n: int,
    content_prefix: str,
    tool: ReportMergingTool,
    directory,
    with_expected_content: bool = True,
    prefix: str = "report-to-merge",
):
    expected_contents = []
    for index in range(n):
        content = f"{content_prefix} {index}"
        if with_expected_content:
            expected_contents.append(content)
        report_path = _write_report(
            directory,
            f"{prefix}-{index}",
            {
                "sdkVersion": get_version(),
                "groupName": content,
                "modelBriefs": [],
                "executions": [],
            },
            {"data-group-id": f"{prefix}-{index}"},
        )
        tool.append(
            {
                "reportFilePath": report_path,
                "reportAttributes": {
                    "testDescription": f"desc{index}",
                    "testDuration": 1,
                    "testId": str(index),
                    "testStatus": "passed",
                    "testTitle": str(index),
                },
            }
        )
    return expected_contents


def test_should_merge_3_mocked_reports(tmp_path):
    """should merge 3 mocked reports"""
    tool = ReportMergingTool()
    expected_contents = generate_n_reports(
        3, "report content", tool, tmp_path, True, "merge-3-test"
    )
    merged_report_path = tool.merge_reports(
        opts={"outputDir": str(tmp_path / "out")}
    )
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    for content in expected_contents:
        assert content in merged_report_content
    # Public merge callers own their input reports unless they explicitly opt
    # into rmOriginalReports.
    for info in tool.report_infos:
        assert Path(info["reportFilePath"]).exists()


def test_should_merge_3_mocked_reports_and_delete_original_reports_after_that(
    tmp_path,
):
    """should merge 3 mocked reports, and delete original reports after that."""
    tool = ReportMergingTool()
    expected_contents = generate_n_reports(
        3,
        "report content, original report file deleted",
        tool,
        tmp_path,
        True,
        "merge-3-delete-test",
    )
    merged_report_path = tool.merge_reports(
        opts={
            "rmOriginalReports": True,
            "overwrite": True,
            "outputDir": str(tmp_path / "out"),
        }
    )
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    for content in expected_contents:
        assert content in merged_report_content
    for info in tool.report_infos:
        assert not Path(info["reportFilePath"]).exists()


def test_should_merge_3_mocked_reports_use_user_custom_filename(tmp_path):
    """should merge 3 mocked reports, use user custom filename"""
    tool = ReportMergingTool()
    expected_contents = generate_n_reports(
        3, "report content", tool, tmp_path, True, "merge-3-custom-name-test"
    )
    merged_report_path = tool.merge_reports(
        "my-custom-merged-report-filename",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    for content in expected_contents:
        assert content in merged_report_content


def test_should_merge_3_mocked_reports_twice_use_user_custom_filename_overwrite_old_report_on_second_merge(
    tmp_path,
):
    """should merge 3 mocked reports twice, use user custom filename, overwrite old report on second merge"""
    tool = ReportMergingTool()
    generate_n_reports(
        3, "report content", tool, tmp_path, True, "merge-3-overwrite-test-1"
    )
    tool.merge_reports(
        "my-custom-merged-report-filename-overwrite",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    tool.clear()
    expected_contents = generate_n_reports(
        3, "new report content", tool, tmp_path, True, "merge-3-overwrite-test-2"
    )
    merged_report_path = tool.merge_reports(
        "my-custom-merged-report-filename-overwrite",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    for content in expected_contents:
        assert content in merged_report_content


def test_should_merge_100_mocked_reports_and_delete_original_reports_after_that(
    tmp_path,
):
    """should merge 100 mocked reports, and delete original reports after that."""
    tool = ReportMergingTool()
    merged_report_path = None
    mocked_report_content = "a" * (4 * 1024)
    generate_n_reports(
        100,
        "mocked report content, original report file will be deleted after "
        f"merge\n{mocked_report_content}",
        tool,
        tmp_path,
        False,
        "merge-100-delete-test",
    )
    try:
        merged_report_path = tool.merge_reports(
            "merge-100-reports",
            {
                "rmOriginalReports": True,
                "overwrite": True,
                "outputDir": str(tmp_path / "out"),
            },
        )
        assert merged_report_path is not None
        assert Path(merged_report_path).exists()
        for info in tool.report_infos:
            assert not Path(info["reportFilePath"]).exists()
    finally:
        if merged_report_path:
            Path(merged_report_path).unlink(missing_ok=True)


def test_should_merge_directory_mode_reports_and_copy_screenshots(tmp_path):
    """should merge directory mode reports and copy screenshots"""
    tool = ReportMergingTool()
    for report_index in range(2):
        report_dir = tmp_path / f"report-{report_index}"
        screenshots_dir = report_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        (screenshots_dir / f"img-{report_index}-0.png").write_text(
            f"fake-png-{report_index}-0", encoding="utf-8"
        )
        (screenshots_dir / f"img-{report_index}-1.png").write_text(
            f"fake-png-{report_index}-1", encoding="utf-8"
        )
        dump_json = json.dumps(
            {
                "sdkVersion": get_version(),
                "groupName": f"test-{report_index}",
                "modelBriefs": [],
                "executions": [
                    {
                        "id": f"dir-{report_index}",
                        "logTime": 0,
                        "name": f"directory {report_index}",
                        "tasks": [
                            {
                                "taskId": f"task-{report_index}",
                                "type": "Log",
                                "status": "finished",
                                "param": {},
                                "recorder": [
                                    {
                                        "type": "screenshot",
                                        "ts": frame_index,
                                        "screenshot": {
                                            "type": "midscene_screenshot_ref",
                                            "id": f"img-{report_index}-{frame_index}",
                                            "capturedAt": frame_index,
                                            "mimeType": "image/png",
                                            "storage": "file",
                                            "path": (
                                                "./screenshots/"
                                                f"img-{report_index}-{frame_index}.png"
                                            ),
                                        },
                                    }
                                    for frame_index in (0, 1)
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        (report_dir / "index.html").write_text(
            f"{get_report_tpl()}\n"
            f'<script type="midscene_web_dump">{dump_json}</script>',
            encoding="utf-8",
        )
        tool.append(
            {
                "reportFilePath": str(report_dir / "index.html"),
                "reportAttributes": {
                    "testDescription": f"desc{report_index}",
                    "testDuration": 1,
                    "testId": str(report_index),
                    "testStatus": "passed",
                    "testTitle": f"test-{report_index}",
                },
            }
        )

    merged_path = tool.merge_reports(
        "dir-mode-merge-test",
        {
            "outputFormat": "html-and-external-assets",
            "overwrite": True,
            "outputDir": str(tmp_path / "out"),
        },
    )

    assert Path(merged_path).exists()
    assert merged_path.endswith("index.html")

    merged_screenshots_dir = Path(merged_path).parent / "screenshots"
    assert merged_screenshots_dir.exists()

    copied_files = sorted(path.name for path in merged_screenshots_dir.iterdir())
    assert len(copied_files) == 4
    contents = []
    for script in read_report_dump_scripts(merged_path):
        parsed = json.loads(script["content"])
        for frame in parsed["executions"][0]["tasks"][0]["recorder"]:
            contents.append(
                (
                    Path(merged_path).parent / frame["screenshot"]["path"]
                ).read_text(encoding="utf-8")
            )
    assert sorted(contents) == [
        "fake-png-0-0",
        "fake-png-0-1",
        "fake-png-1-0",
        "fake-png-1-1",
    ]


def test_should_delete_entire_directory_for_directory_mode_reports_when_rm_original_reports_is_true(
    tmp_path,
):
    """should delete entire directory for directory mode reports when rmOriginalReports is true"""
    tool = ReportMergingTool()
    report_dirs = []
    for report_index in range(2):
        report_dir = tmp_path / f"report-rm-{report_index}"
        screenshots_dir = report_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        report_dirs.append(report_dir)
        (screenshots_dir / f"img-{report_index}.png").write_text(
            f"fake-png-{report_index}", encoding="utf-8"
        )
        dump_json = json.dumps(
            {"groupName": f"test-{report_index}", "executions": []}
        )
        (report_dir / "index.html").write_text(
            f"{get_report_tpl()}\n"
            f'<script type="midscene_web_dump">{dump_json}</script>',
            encoding="utf-8",
        )
        tool.append(
            {
                "reportFilePath": str(report_dir / "index.html"),
                "reportAttributes": {
                    "testDescription": f"desc{report_index}",
                    "testDuration": 1,
                    "testId": str(report_index),
                    "testStatus": "passed",
                    "testTitle": f"test-{report_index}",
                },
            }
        )

    merged_path = tool.merge_reports(
        "dir-mode-rm-test",
        {
            "outputFormat": "html-and-external-assets",
            "rmOriginalReports": True,
            "overwrite": True,
            "outputDir": str(tmp_path / "out"),
        },
    )

    assert Path(merged_path).exists()
    for directory in report_dirs:
        assert not directory.exists()


def _write_dir_mode_report(report_dir, name: str, with_screenshots: bool) -> str:
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    if with_screenshots:
        screenshots_dir = Path(report_dir) / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        (screenshots_dir / "img.png").write_text("fake-png", encoding="utf-8")
    dump_json = json.dumps({"groupName": name, "executions": []})
    index_html = Path(report_dir) / "index.html"
    index_html.write_text(
        f"{get_report_tpl()}\n"
        f'<script type="midscene_web_dump" data-group-id="{name}" '
        f'data-screenshot-mode="directory">{dump_json}</script>',
        encoding="utf-8",
    )
    return str(index_html)


def test_detects_directory_mode_from_metadata_even_without_a_screenshots_dir(
    tmp_path,
):
    """detects directory mode from metadata even without a screenshots dir"""
    no_shots = _write_dir_mode_report(tmp_path / "no-shots", "no-shots", False)
    with_shots = _write_dir_mode_report(
        tmp_path / "with-shots", "with-shots", True
    )
    assert is_directory_mode_report(no_shots) is True
    assert is_directory_mode_report(with_shots) is True


def test_removes_the_whole_directory_of_a_screenshot_less_directory_mode_report_on_rm_original_reports(
    tmp_path,
):
    """removes the whole directory of a screenshot-less directory mode report on rmOriginalReports"""
    tool = ReportMergingTool()
    report_dirs = []
    for name, with_shots in (("with-shots", True), ("no-shots", False)):
        report_dir = tmp_path / name
        report_dirs.append(report_dir)
        index_html = _write_dir_mode_report(report_dir, name, with_shots)
        tool.append(
            {
                "reportFilePath": index_html,
                "reportAttributes": {
                    "testDescription": name,
                    "testDuration": 1,
                    "testId": name,
                    "testStatus": "passed",
                    "testTitle": name,
                },
            }
        )

    merged_path = tool.merge_reports(
        "dir-mode-noss-rm-test",
        {
            "outputFormat": "html-and-external-assets",
            "rmOriginalReports": True,
            "overwrite": True,
            "outputDir": str(tmp_path / "out"),
        },
    )

    assert Path(merged_path).exists()
    for directory in report_dirs:
        assert not directory.exists()


def test_removes_the_folder_of_a_legacy_inline_screenshot_directory_report_on_rm_original_reports(
    tmp_path,
):
    """removes the folder of a legacy inline-screenshot directory report on rmOriginalReports"""
    tool = ReportMergingTool()
    report_dirs = []
    for name in ("playwright-merged-a", "playwright-merged-b"):
        report_dir = tmp_path / name
        report_dir.mkdir(parents=True, exist_ok=True)
        report_dirs.append(report_dir)
        dump_json = json.dumps({"groupName": name, "executions": []})
        (report_dir / "index.html").write_text(
            f"{get_report_tpl()}\n"
            f'<script type="midscene_web_dump" data-group-id="{name}">'
            f"{dump_json}</script>\n"
            + generate_image_script_tag(
                f"{name}-img", "data:image/png;base64,AAAA"
            ),
            encoding="utf-8",
        )
        tool.append(
            {
                "reportFilePath": str(report_dir / "index.html"),
                "reportAttributes": {
                    "testDescription": name,
                    "testDuration": 1,
                    "testId": name,
                    "testStatus": "passed",
                    "testTitle": name,
                },
            }
        )

    merged_path = tool.merge_reports(
        "legacy-folder-rm-test",
        {
            "rmOriginalReports": True,
            "overwrite": True,
            "outputDir": str(tmp_path / "out"),
        },
    )

    assert Path(merged_path).exists()
    assert not merged_path.endswith("index.html")
    for directory in report_dirs:
        assert not directory.exists()


def test_should_merge_a_single_report(tmp_path):
    """should merge a single report"""
    tool = ReportMergingTool()
    generate_n_reports(
        1, "single report content", tool, tmp_path, True, "merge-1-test"
    )
    merged_report_path = tool.merge_reports(
        "single-report-merge",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    assert merged_report_path is not None
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    assert "single report content 0" in merged_report_content


def test_should_handle_reports_with_undefined_report_file_path(tmp_path):
    """should handle reports with undefined reportFilePath (e.g. skipped tests)"""
    tool = ReportMergingTool()
    generate_n_reports(
        1, "normal report", tool, tmp_path, True, "merge-with-skipped"
    )
    tool.append(
        {
            "reportFilePath": None,
            "reportAttributes": {
                "testDescription": "skipped test desc",
                "testDuration": 0,
                "testId": "skipped-1",
                "testStatus": "skipped",
                "testTitle": "Skipped Test",
            },
        }
    )

    merged_report_path = tool.merge_reports(
        "merge-with-skipped-test",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    assert merged_report_path is not None
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    assert "normal report 0" in merged_report_content
    assert 'playwright_test_id="skipped-1"' in merged_report_content
    assert 'playwright_test_status="skipped"' in merged_report_content

    dump_scripts = [
        script
        for script in extract_all_dump_scripts_sync(merged_report_path)
        if "playwright_test_id=" in script["openTag"]
    ]
    skipped_dump = next(
        (
            script
            for script in dump_scripts
            if 'playwright_test_id="skipped-1"' in script["openTag"]
        ),
        None,
    )
    assert skipped_dump is not None
    assert json.loads(skipped_dump["content"])["executions"] == []


def test_should_reject_a_missing_report_file_path_for_non_skipped_tests():
    """should reject a missing reportFilePath for non-skipped tests"""
    tool = ReportMergingTool()
    with pytest.raises(ValueError) as error:
        tool.append(
            {
                "reportFilePath": None,
                "reportAttributes": {
                    "testDescription": "passed test desc",
                    "testDuration": 1,
                    "testId": "passed-1",
                    "testStatus": "passed",
                    "testTitle": "Passed Test",
                },
            }
        )
    assert (
        'reportFilePath is required unless reportAttributes.testStatus is "skipped"'
        in str(error.value)
    )


def test_should_return_null_when_no_reports_are_appended(tmp_path):
    """should return null when no reports are appended"""
    tool = ReportMergingTool()
    merged_report_path = tool.merge_reports(
        "empty-merge",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    assert merged_report_path is None


def test_should_merge_when_all_reports_have_undefined_report_file_path(tmp_path):
    """should merge when all reports have undefined reportFilePath"""
    tool = ReportMergingTool()
    tool.append(
        {
            "reportFilePath": None,
            "reportAttributes": {
                "testDescription": "all skipped 1",
                "testDuration": 0,
                "testId": "all-skipped-1",
                "testStatus": "skipped",
                "testTitle": "All Skipped 1",
            },
        }
    )
    tool.append(
        {
            "reportFilePath": None,
            "reportAttributes": {
                "testDescription": "all skipped 2",
                "testDuration": 0,
                "testId": "all-skipped-2",
                "testStatus": "skipped",
                "testTitle": "All Skipped 2",
            },
        }
    )

    merged_report_path = tool.merge_reports(
        "merge-all-skipped",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )
    assert merged_report_path is not None
    merged_report_content = Path(merged_report_path).read_text(encoding="utf-8")
    assert 'playwright_test_id="all-skipped-1"' in merged_report_content
    assert 'playwright_test_id="all-skipped-2"' in merged_report_content
    assert "For Agent Analysis:" in merged_report_content
    assert merged_report_content.count("<!--\nFor Agent Analysis:") == 1
    assert (
        'Structured report JSON is stored in script[type="midscene_web_dump"] '
        "tags near this comment." in merged_report_content
    )

    dump_scripts = [
        script
        for script in extract_all_dump_scripts_sync(merged_report_path)
        if "playwright_test_id=" in script["openTag"]
    ]
    assert len(dump_scripts) == 2
    for script in dump_scripts:
        assert json.loads(script["content"])["executions"] == []


def test_should_use_constant_memory_when_merging_reports_with_large_inline_images(
    tmp_path,
):
    """should use constant memory when merging reports with large inline images"""
    tool = ReportMergingTool()
    num_reports = 5
    images_per_report = 10
    image_size = 100 * 1024

    for report_index in range(num_reports):
        report_path = tmp_path / f"report-{report_index}.html"
        image_scripts = ""
        for image_index in range(images_per_report):
            fake_base64 = f"data:image/png;base64,{'A' * image_size}"
            image_scripts += (
                generate_image_script_tag(
                    f"img-{report_index}-{image_index}", fake_base64
                )
                + "\n"
            )
        content = (
            f"{get_report_tpl()}\n"
            f"{image_scripts}\n"
            + generate_dump_script_tag(
                json.dumps(
                    {
                        "sdkVersion": get_version(),
                        "groupName": f"test-{report_index}",
                        "modelBriefs": [],
                        "executions": [
                            {
                                "id": f"large-{report_index}",
                                "name": f"large {report_index}",
                                "logTime": 0,
                                "tasks": [
                                    {
                                        "taskId": f"task-{report_index}",
                                        "type": "Log",
                                        "status": "finished",
                                        "param": {
                                            "images": [
                                                {
                                                    "type": "midscene_image_url_ref",
                                                    "id": (
                                                        f"img-{report_index}-"
                                                        f"{image_index}"
                                                    ),
                                                    "mimeType": "image/png",
                                                    "storage": "inline",
                                                }
                                                for image_index in range(
                                                    images_per_report
                                                )
                                            ]
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                {"data-group-id": f"large-{report_index}"},
            )
        )
        report_path.write_text(content, encoding="utf-8")
        tool.append(
            {
                "reportFilePath": str(report_path),
                "reportAttributes": {
                    "testDescription": f"Report {report_index}",
                    "testDuration": 1000,
                    "testId": f"test-{report_index}",
                    "testStatus": "passed",
                    "testTitle": f"Test {report_index}",
                },
            }
        )

    merged_path = tool.merge_reports(
        "memory-test-merged",
        {"overwrite": True, "outputDir": str(tmp_path / "out")},
    )

    assert Path(merged_path).exists()
    merged_content = Path(merged_path).read_text(encoding="utf-8")

    found_images = 0
    for report_index in range(num_reports):
        for image_index in range(images_per_report):
            if f'data-id="img-{report_index}-{image_index}"' in merged_content:
                found_images += 1
    assert found_images == num_reports * images_per_report

    for report_index in range(num_reports):
        for image_index in range(images_per_report):
            assert f'data-id="img-{report_index}-{image_index}"' in merged_content
            assert "AAAAAAAAAA" in merged_content


def test_should_store_a_shared_inline_reference_image_once_when_merging_reports(
    tmp_path,
):
    """should store a shared inline reference image once when merging reports"""
    tool = ReportMergingTool()
    reference_image = f"data:image/webp;base64,{'A' * (64 * 1024)}"
    image_id = "reference-shared-image"

    for index in range(2):
        report_path = tmp_path / f"source-{index}.html"
        dump = {
            "sdkVersion": get_version(),
            "groupName": f"source-{index}",
            "modelBriefs": [],
            "executions": [
                {
                    "id": f"ref-{index}",
                    "name": "reference",
                    "logTime": 0,
                    "tasks": [
                        {
                            "taskId": f"ref-{index}",
                            "type": "Log",
                            "status": "finished",
                            "param": {
                                "image": {
                                    "type": "midscene_image_url_ref",
                                    "id": image_id,
                                    "mimeType": "image/webp",
                                    "storage": "inline",
                                }
                            },
                            "recorder": [],
                        }
                    ],
                }
            ],
        }
        report_path.write_text(
            "\n".join(
                [
                    get_report_tpl(),
                    generate_image_script_tag(image_id, reference_image),
                    generate_dump_script_tag(
                        json.dumps(dump),
                        {"data-group-id": f"group-{index}"},
                    ),
                ]
            ),
            encoding="utf-8",
        )
        tool.append(
            {
                "reportFilePath": str(report_path),
                "reportAttributes": {
                    "testDescription": f"Source {index}",
                    "testDuration": 1,
                    "testId": f"source-{index}",
                    "testStatus": "passed",
                    "testTitle": f"Source {index}",
                },
            }
        )

    merged_report_path = tool.merge_reports(
        "merged-image-dedup",
        {"outputDir": str(tmp_path), "overwrite": True},
    )
    merged_report = Path(merged_report_path).read_text(encoding="utf-8")

    assert len(merged_report.split(reference_image)) == 2
    assert parse_image_scripts(merged_report)[image_id] == reference_image
