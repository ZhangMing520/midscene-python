"""
Logging configuration for Midscene Python
"""

from __future__ import annotations

import contextvars
import inspect
import sys
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from loguru import logger

from midscene.shared.common import get_midscene_run_sub_dir

if TYPE_CHECKING:
    from loguru import Logger

# Console handler/scope context (upstream runWithConsoleLogHandler / Scope).
_console_handler: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = (
    contextvars.ContextVar("midscene_console_handler", default=None)
)
_console_scope: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "midscene_console_scope", default=None
)

_T = TypeVar("_T")


_log_directory_resolver: Callable[[], str] | None = None


def set_log_directory_resolver(
    resolver: Callable[[], str] | None,
) -> None:
    """Override the directory used by file logs in the current process.

    Callers that do not configure a resolver keep the standard
    ``midscene_run/log`` location. This is process-local so an app can isolate
    its logs without changing the run directory itself.
    """
    global _log_directory_resolver
    _log_directory_resolver = resolver


def get_log_directory() -> str:
    """Return the directory file-log sinks should write to."""
    if _log_directory_resolver is not None:
        return _log_directory_resolver()
    return get_midscene_run_sub_dir("log")


def _console_warn(*args: Any) -> None:
    """Default console warning sink; tests replace this with a recorder."""
    print("[Midscene]", *args, file=sys.stderr)


def _debug_fn(*args: Any) -> None:
    """Default debug sink (upstream `debug` package)."""
    logger.debug(_format_args(args))


def _format_value(value: Any) -> str:
    if isinstance(value, BaseException):
        return f"Error: {value}"
    return str(value)


def _format_args(args: Iterable[Any]) -> str:
    return " ".join(_format_value(value) for value in args)


@overload
def run_with_console_log_handler(
    handler: Callable[[dict[str, Any]], None], run: Callable[[], Awaitable[_T]]
) -> Awaitable[_T]: ...


@overload
def run_with_console_log_handler(
    handler: Callable[[dict[str, Any]], None], run: Callable[[], _T]
) -> _T: ...


def run_with_console_log_handler(
    handler: Callable[[dict[str, Any]], None], run: Callable[[], Any]
) -> Any:
    """Route SDK console messages within one run (upstream runWithConsoleLogHandler)."""
    if inspect.iscoroutinefunction(run):
        async_run = cast(Callable[[], Awaitable[_T]], run)

        async def _run_async() -> _T:
            token = _console_handler.set(handler)
            try:
                return await async_run()
            finally:
                _console_handler.reset(token)

        return _run_async()

    token = _console_handler.set(handler)
    try:
        return run()
    finally:
        _console_handler.reset(token)


@overload
def run_with_console_log_scope(
    scope: dict[str, Any], run: Callable[[], Awaitable[_T]]
) -> Awaitable[_T]: ...


@overload
def run_with_console_log_scope(scope: dict[str, Any], run: Callable[[], _T]) -> _T: ...


def run_with_console_log_scope(scope: dict[str, Any], run: Callable[[], Any]) -> Any:
    """Capture the actual async execution scope, including late logs."""

    def wrap(
        base_handler: Callable[[dict[str, Any]], None],
    ) -> Callable[[dict[str, Any]], None]:
        def _wrapped(entry: dict[str, Any]) -> None:
            merged = dict(scope)
            merged.update(entry.get("scope") or {})
            base_handler({**entry, "scope": merged})

        return _wrapped

    if inspect.iscoroutinefunction(run):
        async_run = cast(Callable[[], Awaitable[_T]], run)

        async def _run_async() -> _T:
            handler = _console_handler.get()
            if handler is None:
                return await async_run()
            token = _console_handler.set(wrap(handler))
            try:
                return await async_run()
            finally:
                _console_handler.reset(token)

        return _run_async()

    handler = _console_handler.get()
    if handler is None:
        return run()
    token = _console_handler.set(wrap(handler))
    try:
        return run()
    finally:
        _console_handler.reset(token)


def log_report(message: str) -> None:
    handler = _console_handler.get()
    if handler is not None:
        handler({"type": "report", "topic": "midscene:report", "message": message})
    else:
        print(message)


def _print_console_warning(
    topic: str,
    args: Any,
    warning: dict[str, Any] | None = None,
) -> None:
    handler = _console_handler.get()
    if handler is not None:
        entry: dict[str, Any] = {
            "type": "warning",
            "topic": topic,
            "message": _format_args(args),
            "args": tuple(args),
        }
        if warning is not None:
            entry["warning"] = warning
        handler(entry)
        return
    try:
        _console_warn("[Midscene]", *args)
    except Exception:
        # Debug logging must not crash callers because console output cannot write.
        pass


def get_debug(
    topic: str,
    options: dict[str, Any] | None = None,
) -> Callable[..., None]:
    """Create a debug logger for `topic` (upstream getDebug)."""
    full_topic = f"midscene:{topic}"
    with_console = bool(options and options.get("console"))
    warning = options.get("warning") if options else None

    if with_console:

        def debug_log_console(*args: Any) -> None:
            _debug_fn(*args)
            _print_console_warning(full_topic, args, warning)

        return debug_log_console

    def debug_log(*args: Any) -> None:
        _debug_fn(*args)

    return debug_log


def setup_logger(
    level: str = "INFO",
    log_file: str | None = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
    format_string: str | None = None,
) -> None:
    """Setup logging configuration

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Log file path
        rotation: Log rotation size/time
        retention: Log retention period
        format_string: Custom format string
    """
    # Remove default logger
    logger.remove()

    # Default format
    if not format_string:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

    # Add console handler
    logger.add(
        sys.stderr,
        level=level,
        format=format_string,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Add file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_path,
            level=level,
            format=format_string,
            rotation=rotation,
            retention=retention,
            backtrace=True,
            diagnose=True,
        )

    logger.info(f"Logger configured with level: {level}")


def get_logger(name: str) -> Logger:
    """Get logger instance

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logger.bind(name=name)


_debug_namespaces: set[str] = set()


def enable_debug(namespace: str) -> None:
    """Enable debug output for a namespace (upstream logger.enableDebug)."""
    if not namespace:
        return
    _debug_namespaces.add(namespace)
    # loguru filters by module name, so enabling the whole SDK is the closest
    # equivalent to the upstream namespace switch.
    logger.enable("midscene")


def is_debug_enabled(namespace: str = "") -> bool:
    """Whether debug output was enabled for a namespace."""
    if not namespace:
        return bool(_debug_namespaces)
    return any(
        namespace == item or namespace.startswith(f"{item}:")
        for item in _debug_namespaces
    )
