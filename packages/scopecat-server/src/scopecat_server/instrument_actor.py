"""Process-local ownership boundary for persistent instrument connections."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Literal, Self

from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.backend import (
    BackendApplyRequest,
    BackendCollectRequest,
    BackendInvokeRequest,
)
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectReceipt,
    InvokeReceipt,
)
from scopecat.sdk.instruments.contracts import InstrumentDescription

from .instrument_backend import (
    ConnectedInstrument,
    InstrumentBackendEndpoint,
    InstrumentHandle,
)


class InstrumentActorError(RuntimeError):
    """Base error for invalid actor lifecycle transitions."""


class InstrumentActorConflict(InstrumentActorError):
    """The requested transition conflicts with current instrument ownership."""


class InstrumentActorShutdown(InstrumentActorError):
    """The registry or actor no longer accepts work."""


@dataclass(frozen=True, slots=True)
class InstrumentBindingKey:
    """Identify the provider binding and contract behind one actor connection."""

    provider_id: str
    binding_fingerprint: str
    contract_fingerprint: str


@dataclass(frozen=True, slots=True)
class InstrumentOwnerKey:
    """Identify one durable control-plane owner and its optional fence."""

    kind: Literal["run", "instrument_session"]
    owner_id: str
    fence: str | None = None


type InstrumentConnector = Callable[[], ConnectedInstrument]
type InstrumentConnection = tuple[InstrumentBackendEndpoint, InstrumentHandle]


class OwnedInstrument:
    """One epoch-fenced view of an actor for a run or direct session."""

    __slots__ = (
        "_actor",
        "_binding",
        "_description",
        "_epoch",
        "_instrument_id",
        "_owner",
        "_reused_connection",
    )

    def __init__(
        self,
        actor: _InstrumentActor,
        *,
        instrument_id: str,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        epoch: int,
        description: InstrumentDescription,
        reused_connection: bool,
    ) -> None:
        self._actor = actor
        self._instrument_id = instrument_id
        self._binding = binding
        self._owner = owner
        self._epoch = epoch
        self._description = description
        self._reused_connection = reused_connection

    @property
    def instrument_id(self) -> str:
        return self._instrument_id

    @property
    def binding(self) -> InstrumentBindingKey:
        return self._binding

    @property
    def owner(self) -> InstrumentOwnerKey:
        return self._owner

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def description(self) -> InstrumentDescription:
        return self._description

    @property
    def reused_connection(self) -> bool:
        return self._reused_connection

    @property
    def assumed_state(self) -> InstrumentStateSnapshot | None:
        return self._actor.assumed_state(self)

    def read_state(self) -> InstrumentStateSnapshot:
        """Read hardware under the actor lock without trusting it before validation."""

        return self._actor.read_state(self)

    def adopt_state(self, state: InstrumentStateSnapshot) -> None:
        """Publish a caller-validated snapshot as this owner's working baseline."""

        self._actor.adopt_state(self, state)

    def invalidate_state(self) -> None:
        self._actor.invalidate_state(self)

    def apply_state(self, request: BackendApplyRequest) -> ApplyReceipt:
        return self._actor.apply_state(self, request)

    def invoke(self, request: BackendInvokeRequest) -> InvokeReceipt:
        return self._actor.invoke(self, request)

    def collect(self, request: BackendCollectRequest) -> CollectReceipt:
        return self._actor.collect(self, request)

    def abort(self) -> None:
        """Stop owner-scoped hardware work before release or fault."""

        self._actor.abort(self)

    def release(self) -> None:
        """Release ownership while leaving a matching connection available."""

        self._actor.release(self)

    def fault(self) -> None:
        """Invalidate this epoch and discard its possibly desynchronized connection."""

        self._actor.fault(self)


class _InstrumentActor:
    """Serialize one physical instrument without treating idle state as observed."""

    def __init__(self, exclusivity_key: str) -> None:
        self._exclusivity_key = exclusivity_key
        self._lock = RLock()
        self._binding: InstrumentBindingKey | None = None
        self._description: InstrumentDescription | None = None
        self._endpoint: InstrumentBackendEndpoint | None = None
        self._handle: InstrumentHandle | None = None
        self._owned: OwnedInstrument | None = None
        self._assumed_state: InstrumentStateSnapshot | None = None
        self._epoch = 0
        self._shutdown = False

    def acquire(
        self,
        *,
        instrument_id: str,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        endpoint: InstrumentBackendEndpoint,
        connect: InstrumentConnector,
    ) -> OwnedInstrument:
        with self._lock:
            if self._shutdown:
                raise InstrumentActorShutdown(
                    f"instrument actor is shut down: {self._exclusivity_key}"
                )
            if self._owned is not None:
                if self._binding != binding or self._endpoint is not endpoint:
                    raise InstrumentActorConflict(
                        "owned instrument cannot change backend binding"
                    )
                raise InstrumentActorConflict(
                    f"instrument is already owned: {self._exclusivity_key}"
                )
            if self._handle is not None and (
                self._binding != binding or self._endpoint is not endpoint
            ):
                self._disconnect_idle()
            reused_connection = self._handle is not None
            if self._handle is None:
                connected = connect()
                self._endpoint = endpoint
                self._handle = connected.handle
                self._description = connected.description
                self._binding = binding
            description = self._description
            assert description is not None
            self._epoch += 1
            owned = OwnedInstrument(
                self,
                instrument_id=instrument_id,
                binding=binding,
                owner=owner,
                epoch=self._epoch,
                description=description,
                reused_connection=reused_connection,
            )
            self._owned = owned
            return owned

    def read_state(self, owned: OwnedInstrument) -> InstrumentStateSnapshot:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            # A failed refresh must not leave a previously observed baseline usable.
            self._assumed_state = None
            return endpoint.read_state(handle)

    def assumed_state(
        self,
        owned: OwnedInstrument,
    ) -> InstrumentStateSnapshot | None:
        with self._lock:
            if self._owned is not owned or owned.epoch != self._epoch:
                return None
            state = self._assumed_state
            return None if state is None else state.model_copy(deep=True)

    def adopt_state(
        self,
        owned: OwnedInstrument,
        state: InstrumentStateSnapshot,
    ) -> None:
        with self._lock:
            self._require_owned(owned)
            self._assumed_state = state.model_copy(deep=True)

    def invalidate_state(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            self._assumed_state = None

    def apply_state(
        self,
        owned: OwnedInstrument,
        request: BackendApplyRequest,
    ) -> ApplyReceipt:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            previous = self._assumed_state
            self._assumed_state = None
            receipt = endpoint.apply_state(handle, request)
            if receipt.status == "not_applied":
                self._assumed_state = previous
            return receipt

    def invoke(
        self,
        owned: OwnedInstrument,
        request: BackendInvokeRequest,
    ) -> InvokeReceipt:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            previous = self._assumed_state
            self._assumed_state = None
            receipt = endpoint.invoke(handle, request)
            if receipt.status == "not_invoked":
                self._assumed_state = previous
            return receipt

    def collect(
        self,
        owned: OwnedInstrument,
        request: BackendCollectRequest,
    ) -> CollectReceipt:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            try:
                receipt = endpoint.collect(handle, request)
            except Exception:
                self._assumed_state = None
                raise
            if receipt.status != "collected":
                self._assumed_state = None
            return receipt

    def abort(self, owned: OwnedInstrument) -> None:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            self._assumed_state = None
            endpoint.abort(handle)

    def release(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            self._owned = None
            self._assumed_state = None
            self._epoch += 1

    def fault(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            self._owned = None
            self._epoch += 1
            self._assumed_state = None
            connection = self._detach_connection()
            if connection is not None:
                self._disconnect(connection)

    def retire_idle(self) -> None:
        """Permanently close this actor without disturbing a published owner."""

        with self._lock:
            if self._shutdown:
                raise InstrumentActorShutdown(
                    f"instrument actor is shut down: {self._exclusivity_key}"
                )
            if self._owned is not None:
                raise InstrumentActorConflict(
                    f"owned instrument cannot be retired: {self._exclusivity_key}"
                )
            self._shutdown = True
            self._assumed_state = None
            self._epoch += 1
            connection = self._detach_connection()
            if connection is not None:
                self._disconnect(connection)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            if self._owned is not None:
                self._assumed_state = None
                self._owned = None
                self._epoch += 1
            connection = self._detach_connection()
            if connection is not None:
                self._disconnect(connection)

    def _require_owned(self, owned: OwnedInstrument) -> InstrumentConnection:
        if (
            self._owned is not owned
            or owned.epoch != self._epoch
            or self._endpoint is None
            or self._handle is None
        ):
            raise InstrumentActorConflict(
                f"stale instrument ownership handle: {self._exclusivity_key}"
            )
        return self._endpoint, self._handle

    def _disconnect_idle(self) -> None:
        connection = self._detach_connection()
        self._epoch += 1
        if connection is not None:
            self._disconnect(connection)

    def _disconnect(self, connection: InstrumentConnection) -> None:
        endpoint, handle = connection
        try:
            endpoint.disconnect(handle)
        except Exception:
            # A failed disconnect must never be followed by a second connection.
            self._shutdown = True
            raise

    def _detach_connection(self) -> InstrumentConnection | None:
        endpoint = self._endpoint
        handle = self._handle
        self._endpoint = None
        self._handle = None
        self._description = None
        self._binding = None
        if endpoint is None or handle is None:
            return None
        return endpoint, handle


class InstrumentActorRetirement:
    """A scoped per-key acquisition gate for an inventory migration."""

    __slots__ = (
        "_lock",
        "_release_gate_action",
        "_released",
        "_retire_idle_action",
    )

    def __init__(
        self,
        *,
        retire_idle: Callable[[], None],
        release_gate: Callable[[], None],
    ) -> None:
        self._retire_idle_action = retire_idle
        self._release_gate_action = release_gate
        self._lock = RLock()
        self._released = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release_gate()

    def retire_idle(self) -> None:
        """Disconnect and remove every actor after pre-gate acquires drain."""

        with self._lock:
            if self._released:
                raise InstrumentActorConflict("instrument retirement gate is released")
            self._retire_idle_action()

    def release_gate(self) -> None:
        """Allow acquisitions again; repeated release is harmless."""

        with self._lock:
            if self._released:
                return
            self._release_gate_action()
            self._released = True


class InstrumentActorRegistry:
    """Own one actor per exclusive resource and fence lifecycle transitions."""

    def __init__(self) -> None:
        self._actors: dict[str, _InstrumentActor] = {}
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._acquiring: dict[str, int] = {}
        self._retirements: dict[str, object] = {}
        self._accepting = True
        self._closed = False

    def acquire(
        self,
        exclusivity_key: str,
        instrument_id: str,
        *,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        endpoint: InstrumentBackendEndpoint,
        connect: InstrumentConnector,
    ) -> OwnedInstrument:
        with self._condition:
            if not self._accepting:
                raise InstrumentActorShutdown("instrument actor registry is shut down")
            if exclusivity_key in self._retirements:
                raise InstrumentActorConflict(
                    f"instrument actor is retiring: {exclusivity_key}"
                )
            actor = self._actors.setdefault(
                exclusivity_key,
                _InstrumentActor(exclusivity_key),
            )
            self._acquiring[exclusivity_key] = (
                self._acquiring.get(exclusivity_key, 0) + 1
            )
        try:
            owned = actor.acquire(
                instrument_id=instrument_id,
                binding=binding,
                owner=owner,
                endpoint=endpoint,
                connect=connect,
            )
        except BaseException:
            self._finish_acquire(exclusivity_key)
            raise

        with self._condition:
            accepting = self._accepting
            retiring = exclusivity_key in self._retirements
            current = self._actors.get(exclusivity_key) is actor
            if accepting and not retiring and current:
                self._finish_acquire_locked(exclusivity_key)
                return owned

        # A lifecycle gate may close during a slow connection. The handle was
        # never published, so discard it before allowing retirement to proceed.
        try:
            with suppress(InstrumentActorConflict):
                owned.fault()
        finally:
            self._finish_acquire(exclusivity_key)
        if not accepting:
            raise InstrumentActorShutdown("instrument actor registry is shut down")
        raise InstrumentActorConflict(
            f"instrument actor is retiring: {exclusivity_key}"
        )

    def begin_retirement(
        self,
        keys: Iterable[str],
    ) -> InstrumentActorRetirement:
        """Fence a non-empty set of keys until its retirement token is released."""

        selected = tuple(dict.fromkeys(keys))
        if not selected or any(not key for key in selected):
            raise ValueError("instrument retirement keys must be non-empty")
        marker = object()
        token = InstrumentActorRetirement(
            retire_idle=lambda: self._retire_idle(selected, marker),
            release_gate=lambda: self._release_retirement(selected, marker),
        )
        with self._condition:
            if not self._accepting:
                raise InstrumentActorShutdown("instrument actor registry is shut down")
            conflicts = tuple(key for key in selected if key in self._retirements)
            if conflicts:
                raise InstrumentActorConflict(
                    f"instrument actor is already retiring: {', '.join(conflicts)}"
                )
            self._retirements.update(dict.fromkeys(selected, marker))
        return token

    def _retire_idle(
        self,
        keys: tuple[str, ...],
        marker: object,
    ) -> None:
        for exclusivity_key in keys:
            with self._condition:
                while (
                    self._retirements.get(exclusivity_key) is marker
                    and self._acquiring.get(exclusivity_key, 0) != 0
                ):
                    self._condition.wait()
                if self._retirements.get(exclusivity_key) is not marker:
                    raise InstrumentActorConflict(
                        "instrument retirement gate is released"
                    )
                actor = self._actors.get(exclusivity_key)
            if actor is None:
                continue
            actor.retire_idle()
            with self._condition:
                if self._retirements.get(exclusivity_key) is not marker:
                    raise InstrumentActorConflict(
                        "instrument retirement gate is released"
                    )
                if self._actors.get(exclusivity_key) is not actor:
                    raise InstrumentActorConflict(
                        "instrument actor changed during retirement"
                    )
                del self._actors[exclusivity_key]

    def _release_retirement(
        self,
        keys: tuple[str, ...],
        marker: object,
    ) -> None:
        with self._condition:
            for exclusivity_key in keys:
                if self._retirements.get(exclusivity_key) is marker:
                    del self._retirements[exclusivity_key]
            self._condition.notify_all()

    def _finish_acquire(self, exclusivity_key: str) -> None:
        with self._condition:
            self._finish_acquire_locked(exclusivity_key)

    def _finish_acquire_locked(self, exclusivity_key: str) -> None:
        count = self._acquiring[exclusivity_key]
        if count == 1:
            del self._acquiring[exclusivity_key]
        else:
            self._acquiring[exclusivity_key] = count - 1
        self._condition.notify_all()

    def stop_accepting(self) -> None:
        """Fence new owners before the service starts draining durable claims."""

        with self._lock:
            self._accepting = False

    def shutdown(self) -> None:
        with self._lock:
            self._accepting = False
            if self._closed:
                return
            self._closed = True
            actors = tuple(self._actors.values())
        errors: list[Exception] = []
        for actor in actors:
            try:
                actor.shutdown()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup(
                "instrument actor shutdown failed",
                errors,
            )


__all__ = [
    "InstrumentActorConflict",
    "InstrumentActorError",
    "InstrumentActorRegistry",
    "InstrumentActorRetirement",
    "InstrumentActorShutdown",
    "InstrumentBindingKey",
    "InstrumentOwnerKey",
    "OwnedInstrument",
]
