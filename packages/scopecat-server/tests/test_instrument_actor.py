from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock, Thread
from typing import override
from uuid import uuid4

import pytest
from scopecat.config.registry.records import ConfigRegistryActivationRecord
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverInvokeRequest,
    DriverPropertyWrite,
    InstrumentDescription,
    InvokeReceipt,
)
from scopecat.sdk.payloads import EMPTY_PAYLOAD_CODECS, PayloadCodecRegistry
from tests.testkit.instrument_drivers import (
    SignalInstrumentDriver,
    number_state,
)

from scopecat_server.instrument_actor import (
    InstrumentActorConflict,
    InstrumentActorRegistry,
    InstrumentActorShutdown,
    InstrumentBindingKey,
    InstrumentOwnerKey,
    OwnedInstrument,
)
from scopecat_server.instrument_backend import (
    ConnectedInstrument,
    InstrumentBackendEndpoint,
    InstrumentHandle,
    InstrumentHandleInvalid,
)


class _TrackingDriver(SignalInstrumentDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.disconnect_count = 0

    def change_from_front_panel(self, value: float) -> None:
        self._state[("test.set_gain/v1", "gain")] = number_state(value)

    @override
    def disconnect(self) -> None:
        self.disconnect_count += 1


class _BlockingReadDriver(_TrackingDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id)
        self.first_entered = Event()
        self.release_first = Event()
        self._counter_lock = Lock()
        self._call_count = 0
        self._active = 0
        self.max_active = 0

    @override
    def read_state(self):
        with self._counter_lock:
            self._call_count += 1
            call_number = self._call_count
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            if call_number == 1:
                self.first_entered.set()
                assert self.release_first.wait(timeout=2)
            return super().read_state()
        finally:
            with self._counter_lock:
                self._active -= 1


class _DriverEndpoint(InstrumentBackendEndpoint):
    def __init__(
        self,
        drivers: list[_TrackingDriver],
        instrument_id: str = "source-0",
        *,
        driver_type: type[_TrackingDriver] = _TrackingDriver,
    ) -> None:
        self._drivers = drivers
        self._instrument_id = instrument_id
        self._driver_type = driver_type
        self._endpoint_id = uuid4().hex
        self._connections: dict[InstrumentHandle, _TrackingDriver] = {}
        self._lock = Lock()

    @property
    @override
    def provider_id(self) -> str:
        return "tests.actor_provider"

    @property
    @override
    def payload_codecs(self) -> PayloadCodecRegistry:
        return EMPTY_PAYLOAD_CODECS

    @override
    def resolve_contracts(
        self,
        config: ConfigProfileSnapshot,
    ) -> InstrumentContractCatalog:
        del config
        raise AssertionError("actor tests do not resolve instrument contracts")

    @override
    def connect(
        self,
        *,
        config: ConfigProfileSnapshot,
        instrument_id: str,
        expected: InstrumentDescription,
    ) -> ConnectedInstrument:
        del config
        connected = self.attach(self._driver_type(instrument_id))
        assert connected.description == expected
        return connected

    def __call__(self) -> ConnectedInstrument:
        return self.attach(self._driver_type(self._instrument_id))

    def attach(self, driver: _TrackingDriver) -> ConnectedInstrument:
        handle = InstrumentHandle(
            endpoint_id=self._endpoint_id,
            token=uuid4().hex,
        )
        with self._lock:
            self._connections[handle] = driver
            self._drivers.append(driver)
        return ConnectedInstrument(handle=handle, description=driver.describe())

    @override
    def read_state(self, handle: InstrumentHandle) -> InstrumentStateSnapshot:
        return self._driver(handle).read_state()

    @override
    def apply_state(
        self,
        handle: InstrumentHandle,
        request: DriverApplyRequest,
    ) -> ApplyReceipt:
        return self._driver(handle).apply_state(request)

    @override
    def invoke(
        self,
        handle: InstrumentHandle,
        request: DriverInvokeRequest,
    ) -> InvokeReceipt:
        return self._driver(handle).invoke(request)

    @override
    def collect(
        self,
        handle: InstrumentHandle,
        request: DriverCollectRequest,
    ) -> CollectReceipt:
        return self._driver(handle).collect(request)

    @override
    def abort(self, handle: InstrumentHandle) -> None:
        self._driver(handle).abort()

    @override
    def disconnect(self, handle: InstrumentHandle) -> None:
        with self._lock:
            driver = self._connections.pop(handle)
        driver.disconnect()

    @override
    def shutdown(self) -> None:
        with self._lock:
            drivers = tuple(self._connections.values())
            self._connections.clear()
        for driver in drivers:
            driver.disconnect()

    def _driver(self, handle: InstrumentHandle) -> _TrackingDriver:
        if handle.endpoint_id != self._endpoint_id:
            raise InstrumentHandleInvalid("foreign instrument handle")
        with self._lock:
            try:
                return self._connections[handle]
            except KeyError as error:
                raise InstrumentHandleInvalid("stale instrument handle") from error


def _binding(
    revision: str = "a",
    *,
    generation: int | None = 1,
) -> InstrumentBindingKey:
    return InstrumentBindingKey(
        provider_id="tests.actor_provider",
        config_content_hash=f"sha256:{revision * 64}",
        config_registry_generation=generation,
    )


def _activation(
    generation: int,
    revision: str,
) -> ConfigRegistryActivationRecord:
    return ConfigRegistryActivationRecord(
        generation=generation,
        action="activation",
        entry_id=f"config-{generation}",
        entry_content_hash=f"sha256:{revision * 64}",
        actor="tests",
    )


def _owner(
    owner_id: str,
    *,
    kind: str = "instrument_session",
) -> InstrumentOwnerKey:
    if kind == "run":
        return InstrumentOwnerKey(kind="run", owner_id=owner_id, fence="lease-1")
    return InstrumentOwnerKey(kind="instrument_session", owner_id=owner_id)


def _endpoint(
    drivers: list[_TrackingDriver],
    instrument_id: str = "source-0",
    *,
    driver_type: type[_TrackingDriver] = _TrackingDriver,
) -> _DriverEndpoint:
    return _DriverEndpoint(
        drivers,
        instrument_id,
        driver_type=driver_type,
    )


def test_release_reuses_connection_but_requires_fresh_observation() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)

    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    assert not first.reused_connection
    observed = first.read_state()
    assert first.assumed_state is None
    first.adopt_state(observed)
    first.release()

    assert first.assumed_state is None
    assert drivers[0].disconnect_count == 0
    drivers[0].change_from_front_panel(7.0)

    second = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-2"),
        endpoint=endpoint,
        connect=endpoint,
    )
    assert second.reused_connection
    assert len(drivers) == 1
    refreshed = second.read_state()
    assert refreshed.properties[0].value == number_state(7.0)
    assert second.assumed_state is None
    second.adopt_state(refreshed)
    second.release()
    registry.shutdown()

    assert drivers[0].disconnect_count == 1


def test_binding_change_is_rejected_while_owned_and_rebinds_while_idle() -> None:
    registry = InstrumentActorRegistry()
    old_drivers: list[_TrackingDriver] = []
    new_drivers: list[_TrackingDriver] = []
    old_endpoint = _endpoint(old_drivers)
    new_endpoint = _endpoint(new_drivers)
    first = registry.acquire(
        "source-0",
        binding=_binding("a"),
        owner=_owner("session-1"),
        endpoint=old_endpoint,
        connect=old_endpoint,
    )

    with pytest.raises(
        InstrumentActorConflict,
        match="cannot change backend binding",
    ):
        registry.acquire(
            "source-0",
            binding=_binding("b"),
            owner=_owner("session-2"),
            endpoint=new_endpoint,
            connect=new_endpoint,
        )
    assert not new_drivers
    assert old_drivers[0].disconnect_count == 0

    first.release()
    second = registry.acquire(
        "source-0",
        binding=_binding("b"),
        owner=_owner("session-2"),
        endpoint=new_endpoint,
        connect=new_endpoint,
    )
    assert not second.reused_connection
    assert old_drivers[0].disconnect_count == 1
    assert len(new_drivers) == 1
    second.release()
    registry.shutdown()


def test_activation_retires_idle_actor_even_when_content_hash_is_unchanged() -> None:
    registry = InstrumentActorRegistry()
    registry.observe_config_activation(_activation(1, "a"))
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    first = registry.acquire(
        "source-0",
        binding=_binding("a", generation=1),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    first.release()

    registry.observe_config_activation(_activation(2, "a"))

    assert drivers[0].disconnect_count == 1
    second = registry.acquire(
        "source-0",
        binding=_binding("a", generation=2),
        owner=_owner("session-2"),
        endpoint=endpoint,
        connect=endpoint,
    )
    assert not second.reused_connection
    assert len(drivers) == 2
    second.release()
    registry.shutdown()


def test_activation_defers_owned_actor_retirement_until_release() -> None:
    registry = InstrumentActorRegistry()
    registry.observe_config_activation(_activation(1, "a"))
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    owned = registry.acquire(
        "source-0",
        binding=_binding("a", generation=1),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )

    registry.observe_config_activation(_activation(2, "b"))

    assert drivers[0].disconnect_count == 0
    owned.adopt_state(owned.read_state())
    owned.release()
    assert drivers[0].disconnect_count == 1
    registry.shutdown()


def test_activation_notifications_are_generation_idempotent() -> None:
    registry = InstrumentActorRegistry()
    registry.observe_config_activation(_activation(1, "a"))
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    owned = registry.acquire(
        "source-0",
        binding=_binding("a", generation=1),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    owned.release()

    registry.observe_config_activation(_activation(2, "b"))
    registry.observe_config_activation(_activation(2, "b"))
    registry.observe_config_activation(_activation(1, "a"))

    assert drivers[0].disconnect_count == 1
    registry.shutdown()


def test_non_active_binding_always_retires_on_release() -> None:
    registry = InstrumentActorRegistry()
    registry.observe_config_activation(_activation(2, "b"))
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    owned = registry.acquire(
        "source-0",
        binding=_binding("a", generation=None),
        owner=_owner("run-1", kind="run"),
        endpoint=endpoint,
        connect=endpoint,
    )

    owned.release()

    assert drivers[0].disconnect_count == 1
    registry.shutdown()


def test_owner_epoch_rejects_stale_handles_and_fault_discards_connection() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("run-1", kind="run"),
        endpoint=endpoint,
        connect=endpoint,
    )
    first.adopt_state(first.read_state())
    first.fault()

    assert drivers[0].disconnect_count == 1
    assert first.assumed_state is None
    with pytest.raises(InstrumentActorConflict, match="stale"):
        first.read_state()

    second = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("run-2", kind="run"),
        endpoint=endpoint,
        connect=endpoint,
    )
    assert not second.reused_connection
    assert len(drivers) == 2
    assert second.epoch > first.epoch
    second.release()
    with pytest.raises(InstrumentActorConflict, match="stale"):
        second.invalidate_state()
    registry.shutdown()


def test_handle_serializes_driver_calls_and_never_exposes_the_driver() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(
        drivers,
        driver_type=_BlockingReadDriver,
    )
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    driver = drivers[0]
    assert isinstance(driver, _BlockingReadDriver)
    assert not hasattr(owned, "driver")

    errors: list[BaseException] = []
    second_attempted = Event()

    def first_read() -> None:
        try:
            owned.read_state()
        except BaseException as error:
            errors.append(error)

    def second_read() -> None:
        second_attempted.set()
        try:
            owned.read_state()
        except BaseException as error:
            errors.append(error)

    first_thread = Thread(target=first_read)
    second_thread = Thread(target=second_read)
    first_thread.start()
    assert driver.first_entered.wait(timeout=2)
    second_thread.start()
    assert second_attempted.wait(timeout=2)
    driver.release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    assert driver.max_active == 1
    owned.release()
    registry.shutdown()


def test_unrelated_instruments_can_connect_concurrently() -> None:
    registry = InstrumentActorRegistry()
    first_entered = Event()
    second_entered = Event()
    handles: list[OwnedInstrument] = []
    errors: list[BaseException] = []
    endpoint = _endpoint([])

    def connector(
        instrument_id: str,
        entered: Event,
        peer_entered: Event,
    ) -> Callable[[], ConnectedInstrument]:
        def connect() -> ConnectedInstrument:
            entered.set()
            assert peer_entered.wait(timeout=2)
            driver = _TrackingDriver(instrument_id)
            return endpoint.attach(driver)

        return connect

    def acquire(
        instrument_id: str,
        entered: Event,
        peer_entered: Event,
    ) -> None:
        try:
            handles.append(
                registry.acquire(
                    instrument_id,
                    binding=_binding(),
                    owner=_owner(f"session-{instrument_id}"),
                    endpoint=endpoint,
                    connect=connector(instrument_id, entered, peer_entered),
                )
            )
        except BaseException as error:
            errors.append(error)

    first_thread = Thread(
        target=acquire,
        args=("source-0", first_entered, second_entered),
    )
    second_thread = Thread(
        target=acquire,
        args=("source-1", second_entered, first_entered),
    )
    first_thread.start()
    second_thread.start()
    first_thread.join(timeout=3)
    second_thread.join(timeout=3)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    assert len(handles) == 2
    for handle in handles:
        handle.release()
    registry.shutdown()


def test_handle_routes_driver_calls_through_one_owner_epoch() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    observed = owned.read_state()
    owned.adopt_state(observed)

    apply_request = DriverApplyRequest(
        assignments=(
            DriverPropertyWrite(
                interface_id="test.set_gain/v1",
                property_id="gain",
                value=number_state(1.0),
            ),
        )
    )
    assert owned.apply_state(apply_request).status == "applied"
    assert owned.assumed_state is None
    owned.adopt_state(observed)

    invoke_request = DriverInvokeRequest(
        interface_id="test.play_program/v1",
        operation_id="play",
    )
    invoke_receipt = owned.invoke(invoke_request)
    assert invoke_receipt.status == "invoked"
    assert owned.assumed_state is None
    assert invoke_receipt.state is not None
    owned.adopt_state(invoke_receipt.state)

    collect_request = DriverCollectRequest(
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        results=(DriverCollectResult(request_id="signal", result_id="signal"),),
    )
    assert owned.collect(collect_request).status == "collected"
    assert owned.assumed_state is not None
    assert drivers[0].applied == [apply_request]
    assert drivers[0].invoked == [invoke_request]
    assert drivers[0].collect_requests == [collect_request]

    owned.release()
    registry.shutdown()


def test_stop_accepting_fences_new_owners_without_interrupting_the_drain() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    endpoint = _endpoint(drivers)
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        endpoint=endpoint,
        connect=endpoint,
    )
    registry.stop_accepting()

    owned.adopt_state(owned.read_state())
    owned.release()
    assert drivers[0].disconnect_count == 0
    with pytest.raises(InstrumentActorShutdown, match="registry"):
        registry.acquire(
            "source-0",
            binding=_binding(),
            owner=_owner("session-2"),
            endpoint=endpoint,
            connect=endpoint,
        )

    registry.shutdown()
    assert drivers[0].disconnect_count == 1


def test_shutdown_invalidates_owned_handles_closes_every_actor_and_gates_acquire() -> (
    None
):
    registry = InstrumentActorRegistry()
    first_drivers: list[_TrackingDriver] = []
    second_drivers: list[_TrackingDriver] = []
    first_endpoint = _endpoint(first_drivers)
    second_endpoint = _endpoint(second_drivers, "source-1")
    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        endpoint=first_endpoint,
        connect=first_endpoint,
    )
    first.adopt_state(first.read_state())
    second = registry.acquire(
        "source-1",
        binding=_binding(),
        owner=_owner("session-2"),
        endpoint=second_endpoint,
        connect=second_endpoint,
    )
    second.release()

    registry.shutdown()
    registry.shutdown()

    assert first.assumed_state is None
    assert first_drivers[0].disconnect_count == 1
    assert second_drivers[0].disconnect_count == 1
    with pytest.raises(InstrumentActorConflict, match="stale"):
        first.read_state()
    with pytest.raises(InstrumentActorShutdown, match="registry"):
        third_endpoint = _endpoint([])
        registry.acquire(
            "source-2",
            binding=_binding(),
            owner=_owner("session-3"),
            endpoint=third_endpoint,
            connect=third_endpoint,
        )
