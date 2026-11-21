"""CLI error type and reporting (upstream cli/cli-error.ts)."""

import sys
from typing import Any, Callable, Optional


class CLIError(Exception):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _default_log(message: Any = None, *optional_params: Any) -> None:
    parts = [str(message)] if message is not None else []
    parts.extend(str(param) for param in optional_params)
    print(" ".join(parts), file=sys.stderr)


def report_cli_error(
    error: BaseException, log: Optional[Callable[..., None]] = None
) -> int:
    logger = log or _default_log
    if isinstance(error, CLIError):
        logger(str(error))
        return error.exit_code

    logger(error)
    return 1


__all__ = ["CLIError", "report_cli_error"]
