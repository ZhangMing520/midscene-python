"""Shared CLI framework (upstream packages/shared/src/cli)."""

from midscene.shared.cli.cli_args import (
    canonicalize_cli_arg_keys,
    format_cli_validation_error,
    get_cli_option_display,
    parse_cli_args,
    parse_value,
)
from midscene.shared.cli.cli_error import CLIError, report_cli_error
from midscene.shared.cli.cli_runner import remove_prefix, run_tools_cli
from midscene.shared.cli.record_command import create_record_cli_command
from midscene.shared.cli.verbose import (
    attach_cli_verbose_dump_listener,
    emit_cli_verbose_event,
    get_cli_verbose_context,
    is_cli_verbose_enabled,
    strip_verbose_flag,
    with_cli_verbose_context,
)

__all__ = [
    "CLIError",
    "attach_cli_verbose_dump_listener",
    "canonicalize_cli_arg_keys",
    "create_record_cli_command",
    "emit_cli_verbose_event",
    "format_cli_validation_error",
    "get_cli_option_display",
    "get_cli_verbose_context",
    "is_cli_verbose_enabled",
    "parse_cli_args",
    "parse_value",
    "remove_prefix",
    "report_cli_error",
    "run_tools_cli",
    "strip_verbose_flag",
    "with_cli_verbose_context",
]
