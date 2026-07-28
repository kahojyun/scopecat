"""Process-local ownership boundary for persistent instrument connections."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from threading import RLock
from typing import Literal

from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentDescription,
    InvokeReceipt,
)
from scopecat.sdk.instruments.driver import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
)

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
        "_owner",
        "_reused_connection",
    )

    def __init__(
        self,
        actor: _InstrumentActor,
        *,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        epoch: int,
        description: InstrumentDescription,
        reused_connection: bool,
    ) -> None:
        self._actor = actor
        self._binding = binding
        self._owner = owner
        self._epoch = epoch
        self._description = description
        self._reused_connection = reused_connection

    @property
    def instrument_id(self) -> str:
        return self._actor.instrument_id

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

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        return self._actor.apply_state(self, request)

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return self._actor.invoke(self, request)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
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

    def __init__(self, instrument_id: str) -> None:
        self.instrument_id = instrument_id
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
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        endpoint: InstrumentBackendEndpoint,
        connect: InstrumentConnector,
    ) -> OwnedInstrument:
        with self._lock:
            if self._shutdown:
                raise InstrumentActorShutdown(
                    f"instrument actor is shut down: {self.instrument_id}"
                )
            if self._owned is not None:
                if self._binding != binding or self._endpoint is not endpoint:
                    raise InstrumentActorConflict(
                        "owned instrument cannot change backend binding"
                    )
                raise InstrumentActorConflict(
                    f"instrument is already owned: {self.instrument_id}"
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
        request: DriverApplyRequest,
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
        request: DriverInvokeRequest,
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
        request: DriverCollectRequest,
    ) -> CollectReceipt:
        with self._lock:
            endpoint, handle = self._require_owned(owned)
            try:
                receipt = endpoint.collect(handle, request)
            except Exception:
                self._assumed_state = None
                raise
            if receipt.status == "unknown":
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
                endpoint, handle = connection
                endpoint.disconnect(handle)

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
                endpoint, handle = connection
                endpoint.disconnect(handle)

    def _require_owned(self, owned: OwnedInstrument) -> InstrumentConnection:
        if (
            self._owned is not owned
            or owned.epoch != self._epoch
            or self._endpoint is None
            or self._handle is None
        ):
            raise InstrumentActorConflict(
                f"stale instrument ownership handle: {self.instrument_id}"
            )
        return self._endpoint, self._handle

    def _disconnect_idle(self) -> None:
        connection = self._detach_connection()
        self._epoch += 1
        if connection is not None:
            endpoint, handle = connection
            endpoint.disconnect(handle)

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


class InstrumentActorRegistry:
    """Own one actor per instrument and fence acquisition during shutdown."""

    def __init__(self) -> None:
        self._actors: dict[str, _InstrumentActor] = {}
        self._lock = RLock()
        self._accepting = True
        self._closed = False

    def acquire(
        self,
        instrument_id: str,
        *,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        endpoint: InstrumentBackendEndpoint,
        connect: InstrumentConnector,
    ) -> OwnedInstrument:
        with self._lock:
            if not self._accepting:
                raise InstrumentActorShutdown("instrument actor registry is shut down")
            actor = self._actors.setdefault(
                instrument_id,
                _InstrumentActor(instrument_id),
            )
        owned = actor.acquire(
            binding=binding,
            owner=owner,
            endpoint=endpoint,
            connect=connect,
        )
        with self._lock:
            accepting = self._accepting
        if accepting:
            return owned
        # Shutdown may start during a slow connection. Do not publish a usable
        # handle after the registry gate has closed.
        with suppress(InstrumentActorConflict):
            owned.fault()
        raise InstrumentActorShutdown("instrument actor registry is shut down")

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
    "InstrumentActorShutdown",
    "InstrumentBindingKey",
    "InstrumentOwnerKey",
    "OwnedInstrument",
]
