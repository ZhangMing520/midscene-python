"""Recorder test generation (upstream workflows/recorder-generation)."""

from midscene.core.ai_model.workflows.recorder_generation.common import (
    create_event_counts,
    prepare_event_summary,
    process_events_for_llm,
    stringify_target_block,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.markdown import (
    create_recorder_markdown_replay_prompt,
    generate_markdown_replay,
    limit_screenshot_assets_for_markdown_replay,
    normalize_generated_markdown,
    prepare_screenshot_assets_for_markdown_replay,
)
from midscene.core.ai_model.workflows.recorder_generation.playwright import (
    generate_playwright_test,
)
from midscene.core.ai_model.workflows.recorder_generation.yaml import (
    create_default_web_target,
    create_yaml_prompt,
    generate_yaml_test,
    normalize_generated_yaml,
)

__all__ = [
    "create_default_web_target",
    "create_event_counts",
    "create_recorder_markdown_replay_prompt",
    "create_yaml_prompt",
    "generate_markdown_replay",
    "generate_playwright_test",
    "generate_yaml_test",
    "limit_screenshot_assets_for_markdown_replay",
    "normalize_generated_markdown",
    "prepare_screenshot_assets_for_markdown_replay",
    "normalize_generated_yaml",
    "prepare_event_summary",
    "process_events_for_llm",
    "stringify_target_block",
    "validate_events",
]
