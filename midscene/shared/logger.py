"""
Logging configuration for Midscene Python
"""

import contextvars
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger

# Console handler/scope context (upstream runWithConsoleLogHandler / Scope).
_console_handler: contextvars.ContextVar = contextvars.ContextVar(
    "midscene_console_handler", default=None
)
_console_scope: contextvars.ContextVar = contextvars.ContextVar(
    "midscene_console_scope", default=None
)


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


def _format_args(args: Any) -> str:
    return " ".join(_format_value(value) for value in args)


def run_with_console_log_handler(
    handler: Callable[[Dict[str, Any]], None], run: Callable[[], Any]
) -> Any:
    """Route SDK console messages within one run (upstream runWithConsoleLogHandler)."""
    if inspect.iscoroutinefunction(run):
        async def _run_async():
            token = _console_handler.set(handler)
            try:
                return await run()
            finally:
                _console_handler.reset(token)

        return _run_async()

    token = _console_handler.set(handler)
    try:
        return run()
    finally:
        _console_handler.reset(token)


def run_with_console_log_scope(
    scope: Dict[str, Any], run: Callable[[], Any]
) -> Any:
    """Capture the actual async execution scope, including late logs."""
    def wrap(base_handler):
        def _wrapped(entry: Dict[str, Any]) -> None:
            merged = dict(scope)
            merged.update(entry.get("scope") or {})
            base_handler({**entry, "scope": merged})

        return _wrapped

    if inspect.iscoroutinefunction(run):
        async def _run_async():
            handler = _console_handler.get()
            if handler is None:
                return await run()
            token = _console_handler.set(wrap(handler))
            try:
                return await run()
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
    warning: Optional[Dict[str, Any]] = None,
) -> None:
    handler = _console_handler.get()
    if handler is not None:
        entry: Dict[str, Any] = {
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
    options: Optional[Dict[str, Any]] = None,
) -> Callable[..., None]:
    """Create a debug logger for `topic` (upstream getDebug)."""
    full_topic = f"midscene:{topic}"
    with_console = bool(options and options.get("console"))
    warning = options.get("warning") if options else None

    if with_console:
        def debug_log(*args: Any) -> None:
            _debug_fn(*args)
            _print_console_warning(full_topic, args, warning)

        return debug_log

    def debug_log(*args: Any) -> None:
        _debug_fn(*args)

    return debug_log



def setup_logger(
    level: str = "INFO",
    log_file: Optional[str] = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
    format_string: Optional[str] = None
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
        diagnose=True
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
            diagnose=True
        )
    
    logger.info(f"Logger configured with level: {level}")


def get_logger(name: str):
    """Get logger instance
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    return logger.bind(name=name)


_debug_namespaces: set = set()


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