"""Process-local ownership boundary for persistent instrument connections."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal

from scopecat.config.registry.records import ConfigRegistryActivationRecord
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateCommand,
    InvokeCommand,
    InvokeReceipt,
)


class InstrumentActorError(RuntimeError):
    """Base error for invalid actor lifecycle transitions."""


class InstrumentActorConflict(InstrumentActorError):
    """The requested transition conflicts with current instrument ownership."""


class InstrumentActorShutdown(InstrumentActorError):
    """The registry or actor no longer accepts work."""


@dataclass(frozen=True, slots=True)
class InstrumentBindingKey:
    """Identify the config-specific driver generation behind one actor."""

    provider_id: str
    config_content_hash: str
    config_registry_generation: int | None


@dataclass(frozen=True, slots=True)
class InstrumentOwnerKey:
    """Identify one durable control-plane owner and its optional fence."""

    kind: Literal["run", "instrument_session"]
    owner_id: str
    fence: str | None = None


@dataclass(slots=True)
class InstrumentOperationLedger:
    """Keep replay evidence scoped to one ownership epoch, never a connection."""

    apply_receipts: dict[str, tuple[InstrumentStateCommand, ApplyReceipt]] = field(
        default_factory=dict
    )
    invoke_receipts: dict[str, tuple[InvokeCommand, InvokeReceipt]] = field(
        default_factory=dict
    )
    collect_receipts: dict[str, tuple[CollectCommand, CollectReceipt]] = field(
        default_factory=dict
    )
    collect_failures: dict[str, tuple[CollectCommand, str]] = field(
        default_factory=dict
    )

    def clear(self) -> None:
        self.apply_receipts.clear()
        self.invoke_receipts.clear()
        self.collect_receipts.clear()
        self.collect_failures.clear()


@dataclass(slots=True)
class InstrumentOwnershipState:
    """Mutable data whose lifetime is exactly one ownership handle."""

    assumed_state: InstrumentStateSnapshot | None = None
    ledger: InstrumentOperationLedger = field(default_factory=InstrumentOperationLedger)

    def clear(self) -> None:
        self.assumed_state = None
        self.ledger.clear()


type InstrumentConnector = Callable[
    [],
    tuple[InstrumentDriver, InstrumentDescription],
]


class OwnedInstrument:
    """One epoch-fenced view of an actor for a run or direct session."""

    __slots__ = (
        "_actor",
        "_binding",
        "_description",
        "_epoch",
        "_owner",
        "_reused_connection",
        "data",
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
        self.data = InstrumentOwnershipState()

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
        state = self.data.assumed_state
        return None if state is None else state.model_copy(deep=True)

    @property
    def ledger(self) -> InstrumentOperationLedger:
        return self.data.ledger

    def read_state(self) -> InstrumentStateSnapshot:
        """Read hardware under the actor lock without trusting it before validation."""

        return self._actor.read_state(self)

    def adopt_state(self, state: InstrumentStateSnapshot) -> None:
        """Publish a caller-validated snapshot as this owner's working baseline."""

        self._actor.adopt_state(self, state)

    def invalidate_state(self) -> None:
        self._actor.invalidate_state(self)

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        return self._actor.apply_state(self, command)

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return self._actor.invoke(self, command)

    def collect(self, command: CollectCommand) -> CollectReceipt:
        return self._actor.collect(self, command)

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
        self._driver: InstrumentDriver | None = None
        self._owned: OwnedInstrument | None = None
        self._epoch = 0
        self._retire_on_release = False
        self._shutdown = False

    def acquire(
        self,
        *,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        connect: InstrumentConnector,
        retire_on_release: bool,
    ) -> OwnedInstrument:
        with self._lock:
            if self._shutdown:
                raise InstrumentActorShutdown(
                    f"instrument actor is shut down: {self.instrument_id}"
                )
            if self._owned is not None:
                if self._binding != binding:
                    raise InstrumentActorConflict(
                        "owned instrument cannot change driver binding"
                    )
                raise InstrumentActorConflict(
                    f"instrument is already owned: {self.instrument_id}"
                )
            if self._driver is not None and (
                self._binding != binding or self._retire_on_release
            ):
                self._disconnect_idle()
            reused_connection = self._driver is not None
            if self._driver is None:
                driver, description = connect()
                self._driver = driver
                self._description = description
                self._binding = binding
            self._retire_on_release = retire_on_release
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
            driver = self._require_owned(owned)
            # A failed refresh must not leave a previously observed baseline usable.
            owned.data.assumed_state = None
            return driver.read_state()

    def adopt_state(
        self,
        owned: OwnedInstrument,
        state: InstrumentStateSnapshot,
    ) -> None:
        with self._lock:
            self._require_owned(owned)
            owned.data.assumed_state = state.model_copy(deep=True)

    def invalidate_state(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            owned.data.assumed_state = None

    def apply_state(
        self,
        owned: OwnedInstrument,
        command: InstrumentStateCommand,
    ) -> ApplyReceipt:
        with self._lock:
            driver = self._require_owned(owned)
            previous = owned.data.assumed_state
            owned.data.assumed_state = None
            receipt = driver.apply_state(command)
            if receipt.status == "not_applied":
                owned.data.assumed_state = previous
            return receipt

    def invoke(
        self,
        owned: OwnedInstrument,
        command: InvokeCommand,
    ) -> InvokeReceipt:
        with self._lock:
            driver = self._require_owned(owned)
            previous = owned.data.assumed_state
            owned.data.assumed_state = None
            receipt = driver.invoke(command)
            if receipt.status == "not_invoked":
                owned.data.assumed_state = previous
            return receipt

    def collect(
        self,
        owned: OwnedInstrument,
        command: CollectCommand,
    ) -> CollectReceipt:
        with self._lock:
            driver = self._require_owned(owned)
            try:
                receipt = driver.collect(command)
            except Exception:
                owned.data.assumed_state = None
                raise
            if receipt.status == "unknown":
                owned.data.assumed_state = None
            return receipt

    def abort(self, owned: OwnedInstrument) -> None:
        with self._lock:
            driver = self._require_owned(owned)
            owned.data.assumed_state = None
            driver.abort()

    def release(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            self._owned = None
            owned.data.clear()
            if self._retire_on_release:
                self._disconnect_retired()
            else:
                self._epoch += 1

    def fault(self, owned: OwnedInstrument) -> None:
        with self._lock:
            self._require_owned(owned)
            self._owned = None
            self._epoch += 1
            owned.data.clear()
            driver = self._detach_connection()
            if driver is not None:
                driver.disconnect()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            if self._owned is not None:
                self._owned.data.clear()
                self._owned = None
                self._epoch += 1
            driver = self._detach_connection()
            if driver is not None:
                driver.disconnect()

    def retire_config_generations_before(self, generation: int) -> None:
        """Disconnect stale idle bindings without interrupting their current owner."""

        with self._lock:
            binding = self._binding
            if binding is None:
                return
            binding_generation = binding.config_registry_generation
            if binding_generation is not None and binding_generation >= generation:
                return
            self._retire_on_release = True
            if self._owned is None:
                self._disconnect_retired()

    def _require_owned(self, owned: OwnedInstrument) -> InstrumentDriver:
        if (
            self._owned is not owned
            or owned.epoch != self._epoch
            or self._driver is None
        ):
            raise InstrumentActorConflict(
                f"stale instrument ownership handle: {self.instrument_id}"
            )
        return self._driver

    def _disconnect_idle(self) -> None:
        driver = self._detach_connection()
        self._epoch += 1
        if driver is not None:
            driver.disconnect()

    def _disconnect_retired(self) -> None:
        driver = self._detach_connection()
        self._epoch += 1
        if driver is not None:
            with suppress(Exception):
                driver.disconnect()

    def _detach_connection(self) -> InstrumentDriver | None:
        driver = self._driver
        self._driver = None
        self._description = None
        self._binding = None
        self._retire_on_release = False
        return driver


class InstrumentActorRegistry:
    """Own one actor per instrument and fence acquisition during shutdown."""

    def __init__(self) -> None:
        self._actors: dict[str, _InstrumentActor] = {}
        self._lock = RLock()
        self._accepting = True
        self._closed = False
        self._config_activation_generation: int | None = None

    def acquire(
        self,
        instrument_id: str,
        *,
        binding: InstrumentBindingKey,
        owner: InstrumentOwnerKey,
        connect: InstrumentConnector,
    ) -> OwnedInstrument:
        with self._lock:
            if not self._accepting:
                raise InstrumentActorShutdown("instrument actor registry is shut down")
            activation_generation = self._config_activation_generation
            binding_generation = binding.config_registry_generation
            retire_on_release = binding_generation is None or (
                activation_generation is not None
                and binding_generation < activation_generation
            )
            actor = self._actors.setdefault(
                instrument_id,
                _InstrumentActor(instrument_id),
            )
        owned = actor.acquire(
            binding=binding,
            owner=owner,
            connect=connect,
            retire_on_release=retire_on_release,
        )
        with self._lock:
            accepting = self._accepting
            activation_generation = self._config_activation_generation
        if accepting:
            if (
                activation_generation is not None
                and binding.config_registry_generation is not None
                and binding.config_registry_generation < activation_generation
            ):
                actor.retire_config_generations_before(activation_generation)
            return owned
        # Shutdown may start during a slow connection. Do not publish a usable
        # handle after the registry gate has closed.
        with suppress(InstrumentActorConflict):
            owned.fault()
        raise InstrumentActorShutdown("instrument actor registry is shut down")

    def observe_config_activation(
        self,
        activation: ConfigRegistryActivationRecord,
    ) -> None:
        """Retire bindings older than the newest committed registry activation."""

        with self._lock:
            current_generation = self._config_activation_generation
            if (
                current_generation is not None
                and activation.generation <= current_generation
            ):
                return
            self._config_activation_generation = activation.generation
            actors = tuple(self._actors.values())
        for actor in actors:
            with suppress(Exception):
                actor.retire_config_generations_before(activation.generation)

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
    "InstrumentOperationLedger",
    "InstrumentOwnerKey",
    "OwnedInstrument",
]
