from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock, Thread
from typing import override

import pytest
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    InstrumentDescription,
    InstrumentStateCommand,
    InvokeCommand,
)
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


def _binding(revision: str = "a") -> InstrumentBindingKey:
    return InstrumentBindingKey(
        provider_id="tests.actor_provider",
        config_content_hash=f"sha256:{revision * 64}",
    )


def _owner(
    owner_id: str,
    *,
    kind: str = "instrument_session",
) -> InstrumentOwnerKey:
    if kind == "run":
        return InstrumentOwnerKey(kind="run", owner_id=owner_id, fence="lease-1")
    return InstrumentOwnerKey(kind="instrument_session", owner_id=owner_id)


def _connector(
    drivers: list[_TrackingDriver],
    instrument_id: str = "source-0",
    *,
    driver_type: type[_TrackingDriver] = _TrackingDriver,
) -> Callable[[], tuple[_TrackingDriver, InstrumentDescription]]:
    def connect() -> tuple[_TrackingDriver, InstrumentDescription]:
        driver = driver_type(instrument_id)
        drivers.append(driver)
        return driver, driver.describe()

    return connect


def test_release_reuses_connection_but_requires_fresh_observation() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    connect = _connector(drivers)

    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        connect=connect,
    )
    assert not first.reused_connection
    observed = first.read_state()
    assert first.assumed_state is None
    first.adopt_state(observed)
    first.ledger.apply_receipts["apply-1"] = (
        InstrumentStateCommand(
            command_id="apply-1",
            instrument_id="source-0",
        ),
        ApplyReceipt(),
    )
    first.release()

    assert first.assumed_state is None
    assert not first.ledger.apply_receipts
    assert drivers[0].disconnect_count == 0
    drivers[0].change_from_front_panel(7.0)

    second = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-2"),
        connect=connect,
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
    first = registry.acquire(
        "source-0",
        binding=_binding("a"),
        owner=_owner("session-1"),
        connect=_connector(old_drivers),
    )

    with pytest.raises(
        InstrumentActorConflict,
        match="cannot change driver binding",
    ):
        registry.acquire(
            "source-0",
            binding=_binding("b"),
            owner=_owner("session-2"),
            connect=_connector(new_drivers),
        )
    assert not new_drivers
    assert old_drivers[0].disconnect_count == 0

    first.release()
    second = registry.acquire(
        "source-0",
        binding=_binding("b"),
        owner=_owner("session-2"),
        connect=_connector(new_drivers),
    )
    assert not second.reused_connection
    assert old_drivers[0].disconnect_count == 1
    assert len(new_drivers) == 1
    second.release()
    registry.shutdown()


def test_owner_epoch_rejects_stale_handles_and_fault_discards_connection() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    connect = _connector(drivers)
    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("run-1", kind="run"),
        connect=connect,
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
        connect=connect,
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
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        connect=_connector(
            drivers,
            driver_type=_BlockingReadDriver,
        ),
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

    def connector(
        instrument_id: str,
        entered: Event,
        peer_entered: Event,
    ) -> Callable[[], tuple[_TrackingDriver, InstrumentDescription]]:
        def connect() -> tuple[_TrackingDriver, InstrumentDescription]:
            entered.set()
            assert peer_entered.wait(timeout=2)
            driver = _TrackingDriver(instrument_id)
            return driver, driver.describe()

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


def test_handle_routes_all_driver_calls_and_keeps_ledger_owner_scoped() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        connect=_connector(drivers),
    )
    observed = owned.read_state()
    owned.adopt_state(observed)

    apply_command = InstrumentStateCommand(
        command_id="apply-1",
        instrument_id="source-0",
    )
    assert owned.apply_state(apply_command).status == "applied"
    assert owned.assumed_state is None
    owned.adopt_state(observed)

    invoke_command = InvokeCommand(
        command_id="invoke-1",
        instrument_id="source-0",
        resource_id="resource-0",
        interface_id="test.play_program/v1",
        operation_id="play",
    )
    invoke_receipt = owned.invoke(invoke_command)
    assert invoke_receipt.status == "invoked"
    assert owned.assumed_state is None
    assert invoke_receipt.state is not None
    owned.adopt_state(invoke_receipt.state)

    collect_command = CollectCommand(
        command_id="collect-1",
        instrument_id="source-0",
        point_index=0,
        point_count=1,
    )
    assert owned.collect(collect_command).status == "collected"
    assert owned.assumed_state is not None
    assert drivers[0].applied == [apply_command]
    assert drivers[0].invoked == [invoke_command]
    assert drivers[0].collect_commands == [collect_command]

    owned.ledger.apply_receipts["apply-1"] = (
        apply_command,
        ApplyReceipt(),
    )
    owned.release()
    assert not owned.ledger.apply_receipts
    registry.shutdown()


def test_stop_accepting_fences_new_owners_without_interrupting_the_drain() -> None:
    registry = InstrumentActorRegistry()
    drivers: list[_TrackingDriver] = []
    owned = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        connect=_connector(drivers),
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
            connect=_connector(drivers),
        )

    registry.shutdown()
    assert drivers[0].disconnect_count == 1


def test_shutdown_invalidates_owned_handles_closes_every_actor_and_gates_acquire() -> (
    None
):
    registry = InstrumentActorRegistry()
    first_drivers: list[_TrackingDriver] = []
    second_drivers: list[_TrackingDriver] = []
    first = registry.acquire(
        "source-0",
        binding=_binding(),
        owner=_owner("session-1"),
        connect=_connector(first_drivers),
    )
    first.adopt_state(first.read_state())
    second = registry.acquire(
        "source-1",
        binding=_binding(),
        owner=_owner("session-2"),
        connect=_connector(second_drivers, "source-1"),
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
        registry.acquire(
            "source-2",
            binding=_binding(),
            owner=_owner("session-3"),
            connect=_connector([]),
        )
