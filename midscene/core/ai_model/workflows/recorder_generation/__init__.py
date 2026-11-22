"""Recorder test generation (upstream workflows/recorder-generation)."""

from midscene.core.ai_model.workflows.recorder_generation.common import (
    create_event_counts,
    create_message_content,
    extract_input_descriptions,
    filter_events_by_type,
    get_screenshots_for_llm,
    prepare_event_summary,
    prepare_recorder_generation_context,
    process_events_for_llm,
    stringify_target_block,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.markdown import (
    convert_record_log_into_markdown,
    create_recorder_markdown_replay_prompt,
    generate_markdown_replay,
    generate_recorder_markdown_replay,
    limit_screenshot_assets_for_markdown_replay,
    normalize_generated_markdown,
    prepare_screenshot_assets_for_markdown_replay,
)
from midscene.core.ai_model.workflows.recorder_generation.metadata import (
    generate_recorder_session_metadata,
)
from midscene.core.ai_model.workflows.recorder_generation.playwright import (
    generate_playwright_test,
    generate_playwright_test_stream,
)
from midscene.core.ai_model.workflows.recorder_generation.yaml import (
    create_default_web_target,
    create_yaml_prompt,
    generate_recorder_yaml_test,
    generate_recorder_yaml_test_stream,
    generate_yaml_test,
    generate_yaml_test_stream,
    normalize_generated_yaml,
)

__all__ = [
    "convert_record_log_into_markdown",
    "create_default_web_target",
    "create_event_counts",
    "create_message_content",
    "create_recorder_markdown_replay_prompt",
    "create_yaml_prompt",
    "extract_input_descriptions",
    "filter_events_by_type",
    "generate_markdown_replay",
    "generate_playwright_test",
    "generate_playwright_test_stream",
    "generate_recorder_markdown_replay",
    "generate_recorder_session_metadata",
    "generate_recorder_yaml_test",
    "generate_recorder_yaml_test_stream",
    "generate_yaml_test",
    "generate_yaml_test_stream",
    "get_screenshots_for_llm",
    "limit_screenshot_assets_for_markdown_replay",
    "normalize_generated_markdown",
    "normalize_generated_yaml",
    "prepare_event_summary",
    "prepare_recorder_generation_context",
    "prepare_screenshot_assets_for_markdown_replay",
    "process_events_for_llm",
    "stringify_target_block",
    "validate_events",
]
