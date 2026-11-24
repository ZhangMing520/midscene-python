"""YAML execution ownership and action signals (upstream yaml/execution-session.ts)."""

from collections.abc import Callable
from typing import Any, Optional
from weakref import WeakKeyDictionary

from midscene.core.test_runner.errors import WorkflowError
from midscene.core.yaml.execution_context import (
    create_execution_context,
    supports_async_context,
)


class YamlExecutionOwnershipError(WorkflowError):
    pass


class _Session:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.children: list[Any] = []
        self.finished = False

    def finish(self, record: Any = None, parent: Optional["_Session"] = None) -> None:
        if self.finished:
            return
        self.finished = True
        stack = _sessions.get(self.agent) or []
        if self in stack:
            stack.remove(self)
        if not stack:
            _sessions.pop(self.agent, None)
        if parent is not None:
            if record is not None:
                parent.children.append(record)
            else:
                parent.children.extend(self.children)


class _Frame:
    def __init__(self, parent: Optional["_Frame"] = None) -> None:
        self.parent = parent
        self.session: _Session | None = None
        self.signals: WeakKeyDictionary[Any, list[dict[str, Any]]] = WeakKeyDictionary()


_sessions: "WeakKeyDictionary[Any, list[_Session]]" = WeakKeyDictionary()
_signals: "WeakKeyDictionary[Any, list[dict[str, Any]]]" = WeakKeyDictionary()
_context = create_execution_context()


def has_active_yaml_execution(agent: Any) -> bool:
    return bool(_sessions.get(agent))


async def run_in_yaml_execution_context(callback: Callable[[], Any]) -> Any:
    frame = _Frame(_context.get())
    token = _context.set(frame)
    try:
        return await callback()
    finally:
        if frame.session is not None:
            frame.session.finish()
        _context.reset(token)


def current_yaml_signal(agent: Any) -> Any:
    if not supports_async_context:
        stack = _signals.get(agent)
        return stack[-1]["signal"] if stack else None
    frame = _context.get()
    while frame is not None:
        stack = frame.signals.get(agent)
        if stack:
            return stack[-1]["signal"]
        frame = frame.parent
    return None


def enter_yaml_action(agent: Any, signal: Any) -> Callable[[], None]:
    scope = _context.get().signals if supports_async_context else _signals
    if scope is None:
        raise RuntimeError("YAML action requires an execution context.")
    stack = scope.get(agent)
    if stack is None:
        stack = []
        scope[agent] = stack
    entry = {"signal": signal}
    stack.append(entry)

    def exit_action() -> None:
        if entry in stack:
            stack.remove(entry)
        if not stack:
            scope.pop(agent, None)

    return exit_action


def enter_yaml_execution(agent: Any, allow_independent_overlap: bool = False) -> Any:
    stack = _sessions.get(agent)
    if stack is None:
        stack = []
        _sessions[agent] = stack
    frame = _context.get() if supports_async_context else None
    parent: _Session | None = None

    if supports_async_context:
        if frame is None or frame.session is not None:
            raise RuntimeError("YAML execution requires a fresh execution context.")
        owner = frame.parent
        while owner is not None:
            if owner.session is not None and owner.session.agent is agent:
                parent = owner.session
                break
            owner = owner.parent
        if parent is not None and parent.finished:
            raise YamlExecutionOwnershipError(
                "Cannot start nested YAML after its owning execution has finished.",
                {"code": "YAML_EXECUTION_SCOPE_CLOSED"},
            )
        if stack and stack[-1] is not parent and not allow_independent_overlap:
            raise YamlExecutionOwnershipError(
                "The same Agent cannot run independent overlapping YAML executions. "
                "Await the active run before starting another.",
                {"code": "YAML_EXECUTION_OVERLAP"},
            )
    else:
        parent = stack[-1] if stack else None

    session = _Session(agent)
    stack.append(session)
    _sessions[agent] = stack
    if frame is not None:
        frame.session = session

    class _Handle:
        is_root = parent is None
        children = session.children

        @staticmethod
        def finish(record: Any = None) -> None:
            session.finish(record, parent)

    return _Handle()
