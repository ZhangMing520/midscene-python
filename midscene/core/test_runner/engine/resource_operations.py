"""Agent/resource operation bookkeeping (upstream engine/resource-operations.ts).

The upstream implementation is built on `AbortSignal`, `WeakMap` and native
promises. This port uses asyncio futures and identity-keyed registries while
preserving the observable contract: acquisition tracking, admission checks,
cancel observation and deferred cleanup.
"""

import asyncio
import datetime
import uuid
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar

from loguru import logger

from midscene.core.test_runner.engine._abort import (
    abort_reason,
    add_abort_listener,
    is_aborted,
    throw_if_aborted,
)
from midscene.core.test_runner.errors import WorkflowError
from midscene.core.test_runner.reporting.sanitize import sanitize_report_error

RESOURCE_CLEANUP_GRACE_MS = 1000
RESOURCE_RECOVERY_GRACE_MS = 30_000
RESOURCE_TEARDOWN_GRACE_MS = 10_000


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


class _ResourceOperation:
    __slots__ = ("signal", "operation_id", "identity", "settled", "blockers")

    def __init__(
        self,
        signal: Any,
        operation_id: str,
        identity: dict[str, Any] | None,
    ) -> None:
        self.signal = signal
        self.operation_id = operation_id
        self.identity = identity
        self.settled = False
        self.blockers: set[_ResourceOperation] = set()


class _CleanupOwner:
    def __init__(self, signal: Any = None) -> None:
        self.resources: set[Any] = set()
        self.signal = signal
        self.blockers: set[_ResourceOperation] = set()


class _CleanupState:
    def __init__(self, operation_id: str | None, blockers: set[_ResourceOperation]):
        self.status = "pending"
        self.operation_id = operation_id
        self.blockers = blockers
        self.error: Any = None


class _ResourceHandle:
    def __init__(self) -> None:
        self.operations: dict[Any, _ResourceOperation] = {}
        self.retiring: set[_CleanupOwner] = set()
        self.cleanup: asyncio.Future | None = None
        self.cleanup_state: _CleanupState | None = None


class _ResourceEntry:
    __slots__ = ("resource", "handle")

    def __init__(self, resource: Any) -> None:
        self.resource = resource
        self.handle = _ResourceHandle()


class _ScopeEntry:
    __slots__ = ("signal", "operations", "resources", "cleanup_owner")

    def __init__(self, signal: Any) -> None:
        self.signal = signal
        self.operations: dict[Any, int] = {}
        self.resources: set[Any] | None = set()
        self.cleanup_owner: _CleanupOwner | None = None


class _SignalEntry:
    __slots__ = ("signal", "value")

    def __init__(self, signal: Any, value: Any) -> None:
        self.signal = signal
        self.value = value


_resources: dict[int, _ResourceEntry] = {}
_scopes: dict[int, _ScopeEntry] = {}
_parents: dict[int, _SignalEntry] = {}
_cleanup_owners: dict[int, _SignalEntry] = {}
_identities: dict[int, _SignalEntry] = {}
_listeners: dict[int, _SignalEntry] = {}


def _signal_entry(store: dict[int, _SignalEntry], signal: Any) -> _SignalEntry:
    key = id(signal)
    entry = store.get(key)
    if entry is None or entry.signal is not signal:
        entry = _SignalEntry(signal, None)
        store[key] = entry
    return entry


def _resource_entry(resource: Any) -> _ResourceEntry:
    key = id(resource)
    entry = _resources.get(key)
    if entry is None or entry.resource is not resource:
        entry = _ResourceEntry(resource)
        _resources[key] = entry
    return entry


def _scope_entry(signal: Any) -> _ScopeEntry:
    key = id(signal)
    entry = _scopes.get(key)
    if entry is None or entry.signal is not signal:
        entry = _ScopeEntry(signal)
        _scopes[key] = entry
    return entry


def _lookup(store: dict[int, _SignalEntry], signal: Any) -> Any:
    entry = store.get(id(signal))
    if entry is None or entry.signal is not signal:
        return None
    return entry.value


_SignalStoreEntry = TypeVar("_SignalStoreEntry", _SignalEntry, _ScopeEntry)


def _remove_signal(store: dict[int, _SignalStoreEntry], signal: Any) -> None:
    entry = store.get(id(signal))
    if entry is not None and entry.signal is signal:
        del store[id(signal)]


def _resource_handle(resource: Any) -> _ResourceHandle:
    return _resource_entry(resource).handle


def anonymous_resource() -> Any:
    """A fresh tracking identity used where upstream passes `{}`."""
    return object()


def get_resource_cleanup_completion(owner: Any) -> asyncio.Future | None:
    entry = _resources.get(id(owner))
    if entry is None or entry.resource is not owner:
        return None
    return entry.handle.cleanup


def _blocking_references(
    blockers: Iterable[_ResourceOperation],
) -> list[dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    visited: set[_ResourceOperation] = set()

    def visit(record: _ResourceOperation) -> None:
        if record in visited:
            return
        visited.add(record)
        if not record.settled:
            reference: dict[str, Any] = {"operationId": record.operation_id}
            if record.identity:
                reference.update(record.identity)
            references[record.operation_id] = reference
        for blocker in record.blockers:
            visit(blocker)

    for blocker in blockers:
        visit(blocker)
    return list(references.values())


def get_resource_cleanup_snapshot(owner: Any) -> dict[str, Any]:
    """Read a copy at the publication boundary; never expose live cleanup state."""
    entry = _resources.get(id(owner))
    state = (
        entry.handle.cleanup_state
        if entry is not None and entry.resource is owner
        else None
    )
    snapshot: dict[str, Any] = {
        "capturedAt": _now_iso(),
        "status": state.status if state is not None else "not-required",
    }
    if state is not None and state.operation_id:
        snapshot["operationId"] = state.operation_id
    if state is not None and state.status == "pending":
        snapshot["blockingOperations"] = _blocking_references(state.blockers)
    if state is not None and state.error is not None:
        snapshot["error"] = sanitize_report_error(state.error)
    return snapshot


def get_pending_scope_operations(signal: Any) -> list[dict[str, Any]]:
    entry = _scopes.get(id(signal))
    if entry is None or entry.signal is not signal:
        return []
    operations: list[_ResourceOperation] = []
    for resource in entry.operations.keys():
        handle = _resources.get(id(resource))
        if handle is not None and handle.resource is resource:
            operations.extend(handle.handle.operations.values())
    return _blocking_references(operations)


def has_pending_resource_operation(resource: Any) -> bool:
    handle = _resources.get(id(resource))
    if handle is None or handle.resource is not resource:
        return False
    return bool(handle.handle.operations)


def link_resource_signal(signal: Any, parent: Any = None) -> None:
    """Resource ancestry is independent of cancellation: cleanup can outlive abort."""
    if parent is not None and parent is not signal:
        _signal_entry(_parents, signal).value = parent


def _owner_signals(signal: Any) -> Iterator[Any]:
    seen: set[int] = set()
    owner = signal
    while owner is not None and id(owner) not in seen:
        seen.add(id(owner))
        yield owner
        owner = _lookup(_parents, owner)


class ResourceScope:
    def __init__(self, signal: Any, scope: _ScopeEntry, parent: Any) -> None:
        self.signal = signal
        self._scope = scope
        self._parent = parent
        self._abort_disposer: Callable[[], None] | None = None

    def abort(self, reason: Any = None) -> None:
        self.signal.abort(reason)

    def dispose(self) -> None:
        if self._abort_disposer is not None:
            self._abort_disposer()
            self._abort_disposer = None
        self._scope.resources = None
        if not self._scope.operations:
            _remove_signal(_scopes, self.signal)


def create_resource_scope(parent: Any = None) -> ResourceScope:
    """Each Case/document owns its cleanup, even when cancellation is shared."""
    from midscene.core.types import AbortSignal

    signal = AbortSignal()
    scope = _ScopeEntry(signal)
    _scopes[id(signal)] = scope
    link_resource_signal(signal, parent)

    def abort_from_parent() -> None:
        signal.abort(abort_reason(parent))

    disposer: Callable[[], None] | None = None
    if parent is not None:
        if is_aborted(parent):
            abort_from_parent()
        else:
            disposer = add_abort_listener(parent, abort_from_parent)
    handle = ResourceScope(signal, scope, parent)
    handle._abort_disposer = disposer
    return handle


def assert_resource_available(
    resource: Any,
    exclusive: bool = False,
    signal: Any = None,
) -> bool:
    entry = _resources.get(id(resource))
    handle = entry.handle if entry is not None and entry.resource is resource else None
    retiring = handle.retiring if handle is not None else set()
    is_owner_cleanup = False
    if signal is not None:
        for owner_signal in _owner_signals(signal):
            owner = _lookup(_cleanup_owners, owner_signal)
            if owner is not None and owner in retiring:
                is_owner_cleanup = True
                break
    if retiring and not is_owner_cleanup:
        raise WorkflowError(
            "A resource cannot execute overlapping Runner operations while its cleanup is pending.",
            {"code": "RESOURCE_CLEANUP_PENDING"},
        )
    pending = handle.operations if handle is not None else {}
    if exclusive and pending:
        raise WorkflowError(
            "The same Agent instance cannot execute overlapping Runner operations.",
            {"code": "RESOURCE_OPERATION_PENDING"},
        )
    if pending and any(is_aborted(op.signal) for op in pending.values()):
        raise WorkflowError(
            "Cannot reuse an Agent while an aborted YAML action or Runner operation is still running.",
            {"code": "RESOURCE_OPERATION_PENDING"},
        )
    return is_owner_cleanup


def observe_resource_operations(
    signal: Any,
    listener: Callable[[dict[str, Any]], None],
) -> Callable[[], None]:
    """Capture subscribers at registration: late settlement stays with its original run."""
    entry = _signal_entry(_listeners, signal)
    subscribers: set[Callable[[dict[str, Any]], None]] | None = entry.value
    if subscribers is None:
        subscribers = set()
        entry.value = subscribers
    subscribers.add(listener)

    def dispose() -> None:
        subscribers.discard(listener)
        if not subscribers:
            _remove_signal(_listeners, signal)

    return dispose


def set_resource_operation_identity(signal: Any, identity: dict[str, Any]) -> None:
    _signal_entry(_identities, signal).value = dict(identity)


class ResourceObservation:
    def __init__(
        self,
        record: _ResourceOperation,
        emit: Callable[..., None],
        settled: Callable[[], bool],
    ) -> None:
        self.record = record
        self._emit = emit
        self._settled = settled

    def runner_returned(self, status: str) -> None:
        self._emit(kind="runner-returned", status=status, pending=not self._settled())

    def cleanup_deferred(self, blockers: Iterable[_ResourceOperation]) -> None:
        self._emit(
            kind="cleanup-deferred",
            blockingOperations=_blocking_references(blockers),
        )


def record_operation(
    operation: Any,
    signal: Any,
    operation_kind: str,
) -> ResourceObservation:
    if asyncio.iscoroutine(operation):
        operation = asyncio.ensure_future(operation)
    owners = list(_owner_signals(signal))
    identity = None
    for owner in owners:
        found = _lookup(_identities, owner)
        if found:
            identity = found
            break
    record = _ResourceOperation(signal, uuid.uuid4().hex, identity)
    subscribers: set[Callable[[dict[str, Any]], None]] = set()
    for owner in owners:
        subscribers.update(_lookup(_listeners, owner) or set())

    def emit(**event: Any) -> None:
        payload: dict[str, Any] = {}
        if identity:
            payload.update(identity)
        payload.update(
            {
                "operationId": record.operation_id,
                "operationKind": operation_kind,
                "at": _now_iso(),
            }
        )
        payload.update(event)
        for subscriber in list(subscribers):
            try:
                subscriber(payload)
            except Exception as error:  # pragma: no cover - observer isolation
                logger.debug(f"Operation observer failed: {error}")

    def abort() -> None:
        emit(kind="cancel-requested", error=sanitize_report_error(abort_reason(signal)))

    emit(kind="started")
    disposer: Callable[[], None] | None = None
    if is_aborted(signal):
        abort()
    else:
        disposer = add_abort_listener(signal, abort)

    def finish(status: str, error: Any = None) -> None:
        record.settled = True
        if disposer is not None:
            disposer()
        payload: dict[str, Any] = {"kind": "settled", "status": status}
        if status != "success":
            payload["error"] = sanitize_report_error(error)
        emit(**payload)

    def on_done(future: asyncio.Future) -> None:
        if future.cancelled():
            finish("failed", asyncio.CancelledError())
            return
        error = future.exception()
        if error is None:
            finish("success")
        else:
            finish(
                "not-run" if is_resource_admission_error(error) else "failed",
                error,
            )

    operation.add_done_callback(on_done)
    return ResourceObservation(record, emit, lambda: record.settled)


class ResourceAdmissionError(WorkflowError):
    """A scheduling decision, distinct from an action that ran and failed."""

    def __init__(
        self,
        code: str,
        blockers: Iterable[_ResourceOperation],
    ) -> None:
        blocker_list = list(blockers)
        super().__init__(
            "The Agent is occupied by an unfinished operation or pending cleanup; this action was not started.",
            {
                "code": code,
                "details": {
                    "blockingOperations": [
                        {
                            "operationId": blocker.operation_id,
                            **(blocker.identity or {}),
                        }
                        for blocker in blocker_list
                    ]
                },
            },
        )
        blocked = [
            blocker.identity.get("stepId")
            for blocker in blocker_list
            if blocker.identity and blocker.identity.get("stepId")
        ]
        self.blocked_by = blocked[0] if blocked else None


def is_resource_admission_error(error: Any) -> bool:
    return isinstance(error, ResourceAdmissionError)


def admit_resource_operation(
    resource: Any,
    signal: Any,
    exclusive: bool = True,
) -> bool:
    try:
        return assert_resource_available(resource, exclusive, signal)
    except WorkflowError as error:
        if error.code in ("RESOURCE_OPERATION_PENDING", "RESOURCE_CLEANUP_PENDING"):
            entry = _resources.get(id(resource))
            handle = (
                entry.handle
                if entry is not None and entry.resource is resource
                else _ResourceHandle()
            )
            blockers: list[_ResourceOperation] = list(handle.operations.values())
            for owner in handle.retiring:
                blockers.extend(owner.blockers)
            raise ResourceAdmissionError(error.code, blockers) from error
        raise


def retain_for_cleanup(owner: _CleanupOwner, resource: Any) -> None:
    owner.resources.add(resource)
    handle = _resource_handle(resource)
    owner.blockers.update(handle.operations.values())
    handle.retiring.add(owner)


def retain_resource_for_scope(resource: Any, signal: Any) -> None:
    """Acquisition establishes cleanup ownership even if action admission is rejected."""
    retained = False
    for owner_signal in _owner_signals(signal):
        scope = _scopes.get(id(owner_signal))
        if scope is not None and scope.signal is owner_signal:
            if not retained and scope.resources is not None:
                scope.resources.add(resource)
                retained = True
            if scope.cleanup_owner is not None:
                retain_for_cleanup(scope.cleanup_owner, resource)


def track_resource_operation(
    resource: Any,
    operation: Any,
    signal: Any,
    kind: str = "resource",
    existing_observation: ResourceObservation | None = None,
) -> Any:
    """Track actual completion, not the Runner timeout race."""
    if asyncio.iscoroutine(operation):
        operation = asyncio.ensure_future(operation)
    observation = existing_observation or record_operation(operation, signal, kind)
    active = _resource_handle(resource).operations
    active[operation] = observation.record

    owner_scopes: list[tuple[Any, _ScopeEntry]] = []
    retained_by_scope = False
    for owner_signal in _owner_signals(signal):
        scope = _scopes.get(id(owner_signal))
        if scope is None or scope.signal is not owner_signal:
            scope = _ScopeEntry(owner_signal)
            _scopes[id(owner_signal)] = scope
        scope.operations[resource] = scope.operations.get(resource, 0) + 1
        owner_scopes.append((owner_signal, scope))
        # Only the closest owner retains idle resources for its teardown. Parents
        # wait on active operations, not every Agent used by completed Cases.
        if not retained_by_scope and scope.resources is not None:
            scope.resources.add(resource)
            retained_by_scope = True
        cleanup_owner = _lookup(_cleanup_owners, owner_signal)
        if cleanup_owner is not None:
            cleanup_owner.blockers.add(observation.record)
            retain_for_cleanup(cleanup_owner, resource)

    def finish(_future: asyncio.Future) -> None:
        active.pop(operation, None)
        for owner_signal, scope in owner_scopes:
            count = scope.operations.get(resource, 0) - 1
            if count > 0:
                scope.operations[resource] = count
            else:
                scope.operations.pop(resource, None)
            if not scope.operations and scope.resources is None:
                _remove_signal(_scopes, owner_signal)
        handle = _resources.get(id(resource))
        if (
            handle is not None
            and handle.resource is resource
            and not handle.handle.operations
            and not handle.handle.retiring
            and handle.handle.cleanup is None
        ):
            del _resources[id(resource)]

    operation.add_done_callback(finish)
    return operation


async def wait_for_resource_idle(resource: Any) -> None:
    while True:
        entry = _resources.get(id(resource))
        if entry is None or entry.resource is not resource:
            return
        operations = list(entry.handle.operations.keys())
        if not operations:
            return
        await asyncio.gather(*operations, return_exceptions=True)


async def wait_for_scope_operations(signal: Any) -> None:
    """Wait for actual descendant settlement, including deferred cleanup."""
    while True:
        entry = _scopes.get(id(signal))
        if entry is None or entry.signal is not signal or not entry.operations:
            return
        await asyncio.gather(
            *(wait_for_resource_idle(resource) for resource in list(entry.operations)),
            return_exceptions=True,
        )


async def recover_cancelled_scope_resources(
    signal: Any,
    grace_ms: float = RESOURCE_RECOVERY_GRACE_MS,
) -> float:
    """Wait for this scope's cancelled work before scheduling its next Step."""
    throw_if_aborted(signal)
    loop = asyncio.get_event_loop()
    started_at = loop.time()

    def pending_operations() -> list[tuple[Any, Any, Any, _ResourceOperation]]:
        pending: list[tuple[Any, Any, Any, _ResourceOperation]] = []
        entry = _scopes.get(id(signal))
        if entry is None or entry.signal is not signal:
            return pending
        for resource in list(entry.operations.keys()):
            handle_entry = _resources.get(id(resource))
            if handle_entry is None or handle_entry.resource is not resource:
                continue
            for operation, tracked in list(handle_entry.handle.operations.items()):
                owner_signal = tracked.signal
                if is_aborted(owner_signal) and signal in list(
                    _owner_signals(owner_signal)
                ):
                    pending.append((operation, owner_signal, resource, tracked))
        return pending

    pending = pending_operations()
    if not pending:
        return 0.0

    stopped: asyncio.Future[Any] = loop.create_future()

    def on_abort() -> None:
        if not stopped.done():
            stopped.set_result(abort_reason(signal))

    def on_timeout() -> None:
        if stopped.done():
            return
        blocking = _blocking_references([item[3] for item in pending])
        step_ids = [item.get("stepId") for item in blocking]
        blocked_by = (
            step_ids[0]
            if step_ids and all(step_id == step_ids[0] for step_id in step_ids)
            else None
        )
        stopped.set_exception(
            WorkflowError(
                f"The previous operation was still running after {grace_ms / 1000} s. Later steps were not started.",
                {
                    "code": "RESOURCE_RECOVERY_TIMEOUT",
                    "details": {
                        "graceMs": grace_ms,
                        "waitedMs": (loop.time() - started_at) * 1000,
                        "resourceCount": len({item[2] for item in pending}),
                        "blockingOperations": blocking,
                        "blockedByStepId": blocked_by,
                    },
                    "cause": abort_reason(pending[0][1]),
                },
            )
        )

    disposer = add_abort_listener(signal, on_abort)
    timer = loop.call_later(grace_ms / 1000.0, on_timeout)
    try:
        while pending:
            waiters = [item[0] for item in pending]
            await asyncio.wait({*waiters, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if stopped.done() and not stopped.cancelled():
                failure = stopped.exception()
                if failure is not None:
                    raise failure
            throw_if_aborted(signal)
            pending = pending_operations()
        return (loop.time() - started_at) * 1000
    finally:
        timer.cancel()
        disposer()
        if not stopped.done():
            stopped.cancel()


class ResourceCleanupDeferredError(WorkflowError):
    def __init__(
        self,
        grace_ms: float,
        resource_count: int,
        blockers: Iterable[_ResourceOperation] = (),
    ) -> None:
        super().__init__(
            f"Resource cleanup did not finish within {grace_ms}ms. Resources remain quarantined until cleanup settles.",
            {
                "code": "RESOURCE_CLEANUP_DEFERRED",
                "details": {
                    "graceMs": grace_ms,
                    "resourceCount": resource_count,
                    "blockingOperations": [
                        {
                            "operationId": blocker.operation_id,
                            **(blocker.identity or {}),
                        }
                        for blocker in blockers
                    ],
                },
            },
        )


async def _run_resource_cleanup(
    resources: list[Any],
    cleanup: Callable[[], Any],
    options: dict[str, Any],
    before_cleanup: dict[str, Any] | None = None,
) -> Any:
    loop = asyncio.get_event_loop()
    owner = _CleanupOwner(before_cleanup.get("signal") if before_cleanup else None)
    for resource in resources:
        retain_for_cleanup(owner, resource)
    if owner.signal is not None:
        _signal_entry(_cleanup_owners, owner.signal).value = owner
    option_signal = options.get("signal")
    owner_scope = _scopes.get(id(option_signal)) if option_signal is not None else None
    if owner_scope is not None and owner_scope.signal is not option_signal:
        owner_scope = None
    if owner_scope is not None:
        owner_scope.cleanup_owner = owner

    deferred: asyncio.Future[Any] = loop.create_future()

    def defer() -> None:
        if deferred.done():
            return
        total_timeout = options.get("totalTimeoutMs")
        if total_timeout is not None and before_cleanup is not None:
            before_cleanup["abort"](
                WorkflowError(
                    f"Resource cleanup timed out after {total_timeout}ms.",
                    {
                        "code": "TEARDOWN_TIMEOUT",
                        "details": {"timeoutMs": total_timeout},
                    },
                )
            )
        if not deferred.done():
            deferred.set_result({"deferred": True})

    total_timeout = options.get("totalTimeoutMs")
    grace_ms = (
        total_timeout
        if total_timeout is not None
        else options.get("graceMs", RESOURCE_CLEANUP_GRACE_MS)
    )

    async def drain() -> None:
        timer = None
        if total_timeout is None:
            timer = loop.call_later(grace_ms / 1000.0, defer)
        try:
            while True:
                pending = [
                    resource
                    for resource in list(owner.resources)
                    if _resource_handle(resource).operations
                ]
                if not pending:
                    return
                await asyncio.gather(
                    *(wait_for_resource_idle(resource) for resource in pending),
                    return_exceptions=True,
                )
        finally:
            if timer is not None:
                timer.cancel()

    async def run_cleanup() -> Any:
        nonlocal grace_ms
        timer = None
        if total_timeout is not None:
            timer = loop.call_later(max(0.0, total_timeout / 1000.0), defer)
        try:
            if before_cleanup is not None:
                await before_cleanup["run"](before_cleanup["signal"])
            await drain()
            if total_timeout is None:
                grace_ms = options.get("graceMs") or RESOURCE_TEARDOWN_GRACE_MS
                timer = loop.call_later(grace_ms / 1000.0, defer)
            return await cleanup()
        finally:
            if timer is not None:
                timer.cancel()
            if owner.signal is not None:
                _remove_signal(_cleanup_owners, owner.signal)
            if owner_scope is not None and owner_scope.cleanup_owner is owner:
                owner_scope.cleanup_owner = None
            for resource in owner.resources:
                _resource_handle(resource).retiring.discard(owner)

    completion = asyncio.ensure_future(run_cleanup())
    cleanup_observation: ResourceObservation | None = None
    if option_signal is not None:
        cleanup_observation = record_operation(completion, option_signal, "cleanup")
    owner_key = options.get("owner")
    if owner_key is None and before_cleanup is not None:
        owner_key = before_cleanup["signal"]
    if owner_key is None and resources:
        owner_key = resources[0]
    cleanup_state = _CleanupState(
        cleanup_observation.record.operation_id if cleanup_observation else None,
        owner.blockers,
    )
    if cleanup_observation is not None:
        cleanup_observation.record.blockers = owner.blockers
    if owner_key is not None:
        handle = _resource_handle(owner_key)
        handle.cleanup = completion
        handle.cleanup_state = cleanup_state

    def mark_outcome(future: asyncio.Future) -> None:
        if future.cancelled() or future.exception() is not None:
            cleanup_state.status = "failed"
            cleanup_state.error = (
                asyncio.CancelledError() if future.cancelled() else future.exception()
            )
        else:
            cleanup_state.status = "completed"

    completion.add_done_callback(mark_outcome)

    await asyncio.wait({completion, deferred}, return_when=asyncio.FIRST_COMPLETED)
    if deferred.done():
        if cleanup_observation is not None:
            cleanup_observation.cleanup_deferred(owner.blockers)

        def report_deferred_error(future: asyncio.Future) -> None:
            if future.cancelled():
                return
            error = future.exception()
            if error is None:
                return
            try:
                options["onDeferredError"](error)
            except Exception:  # pragma: no cover - defensive
                pass

        completion.add_done_callback(report_deferred_error)
        if option_signal is not None:
            track_resource_operation(
                anonymous_resource(),
                completion,
                option_signal,
                "cleanup",
                cleanup_observation,
            )
        raise ResourceCleanupDeferredError(
            grace_ms, len(owner.resources), list(owner.blockers)
        )
    return completion.result()


async def cleanup_resources(
    resources: Iterable[Any],
    cleanup: Callable[[], Any],
    options: dict[str, Any],
) -> Any:
    return await _run_resource_cleanup(list(resources), cleanup, options)


async def cleanup_scope_resources(
    signal: Any,
    cleanup: Callable[[], Any],
    options: dict[str, Any],
) -> Any:
    from midscene.core.types import AbortSignal

    cleanup_signal = AbortSignal()
    link_resource_signal(cleanup_signal, signal)
    scope = _scopes.get(id(signal))
    if scope is not None and scope.signal is not signal:
        scope = None
    resources: list[Any] = []
    if scope is not None and scope.resources is not None:
        resources.extend(scope.resources)
    if scope is not None:
        resources.extend(scope.operations.keys())

    before_cleanup = None
    before_cleanup_fn = options.get("beforeCleanup")
    if before_cleanup_fn is not None:
        before_cleanup = {
            "signal": cleanup_signal,
            "abort": cleanup_signal.abort,
            "run": before_cleanup_fn,
        }
    merged_options = dict(options)
    merged_options["owner"] = signal
    merged_options["signal"] = signal
    return await _run_resource_cleanup(
        resources, cleanup, merged_options, before_cleanup
    )


__all__ = [
    "RESOURCE_CLEANUP_GRACE_MS",
    "RESOURCE_RECOVERY_GRACE_MS",
    "RESOURCE_TEARDOWN_GRACE_MS",
    "ResourceAdmissionError",
    "ResourceCleanupDeferredError",
    "ResourceObservation",
    "ResourceScope",
    "admit_resource_operation",
    "anonymous_resource",
    "assert_resource_available",
    "cleanup_resources",
    "cleanup_scope_resources",
    "create_resource_scope",
    "get_pending_scope_operations",
    "get_resource_cleanup_completion",
    "get_resource_cleanup_snapshot",
    "has_pending_resource_operation",
    "is_resource_admission_error",
    "link_resource_signal",
    "observe_resource_operations",
    "recover_cancelled_scope_resources",
    "record_operation",
    "retain_resource_for_scope",
    "set_resource_operation_identity",
    "track_resource_operation",
    "wait_for_resource_idle",
    "wait_for_scope_operations",
]
