from __future__ import annotations

from typing import Literal, override

from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverPayload,
    DriverRejected,
    DriverStatePatch,
    DriverSuccess,
    DriverUnknown,
    InstrumentDescription,
    InstrumentDriver,
)

from client_codegen_fixture_declarations import (
    DriverMonitorState,
    DriverSourceLeftState,
)
from generated_driver_handler_fixture import (
    ComponentOperationDriverAdapter,
    DriverFixedAcquisitionAcquireDriverReadback,
    DriverFixedAcquisitionDriverAdapter,
    DriverMonitorMonitorDriverReadback,
    DriverSourceDriverAdapter,
    DriverSourceDriverSnapshot,
    LiteralOperationDriverAdapter,
    MonitorCompositeDriverAdapter,
    MonitorCompositeDriverPatch,
    MonitorCompositeDriverSnapshot,
    PayloadOperationDriverAdapter,
)
from generated_driver_state_catalog_fixture import DriverSourceDriverPatch
from generated_member_catalog_fixture import (
    COMPONENT_OPERATION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE,
    DRIVER_FIXED_ACQUISITION_ACQUIRE,
    DRIVER_FIXED_ACQUISITION_RESPONSE_RESULT,
    DRIVER_MONITOR_ACQUISITION,
    DRIVER_MONITOR_ENABLED,
    DRIVER_MONITOR_RIGHT_RESULT,
    DRIVER_SOURCE_ENABLED,
    DRIVER_SOURCE_LEFT_LEVEL,
    DRIVER_SOURCE_MODE,
    DRIVER_SOURCE_RIGHT_LEVEL,
    LITERAL_OPERATION_SELECT,
    PAYLOAD_OPERATION_UPLOAD,
)


class _ComponentDriver(ComponentOperationDriverAdapter):
    instrument_id = "component"

    def __init__(self) -> None:
        self.call: tuple[int, Quantity, str] | None = None

    @override
    def handle_output_trigger_emit(
        self,
        count: int,
        /,
        width: Quantity,
        *,
        label: str,
    ) -> DriverOutcome[None]:
        self.call = (count, width, label)
        return DriverSuccess(None, metadata={"handler": "component"})


class _LiteralDriver(LiteralOperationDriverAdapter):
    instrument_id = "literal"

    def __init__(self) -> None:
        self.selected: Literal["left", "right"] | None = None
        self.rejected = DriverRejected(
            problems=(),
            metadata={"handler": "literal_rejected"},
        )

    @override
    def handle_select(
        self,
        mode: Literal["left", "right"],
    ) -> DriverOutcome[None]:
        self.selected = mode
        if mode == "right":
            return self.rejected
        return DriverSuccess(None)


class _PayloadDriver(PayloadOperationDriverAdapter):
    instrument_id = "payload"

    def __init__(self) -> None:
        self.payload: bytes | None = None
        self.unknown = DriverUnknown(
            problems=(),
            metadata={"handler": "payload_unknown"},
        )

    @override
    def handle_upload(self, payload: bytes) -> DriverOutcome[None]:
        self.payload = payload
        if payload == b"unknown":
            return self.unknown
        return DriverSuccess(None)


class _FixedDriver(DriverFixedAcquisitionDriverAdapter):
    instrument_id = "fixed"

    def __init__(self) -> None:
        self.acquire_calls = 0

    @override
    def handle_acquire(
        self,
    ) -> DriverOutcome[DriverFixedAcquisitionAcquireDriverReadback]:
        self.acquire_calls += 1
        return DriverSuccess(
            DriverFixedAcquisitionAcquireDriverReadback(
                response=_measurement("ratio"),
                metadata={"readback": "fixed"},
            ),
            metadata={"handler": "fixed"},
        )


class _SourceDriver(DriverSourceDriverAdapter):
    instrument_id = "source"

    def __init__(self) -> None:
        self.patch: DriverSourceDriverPatch | None = None

    @override
    def read_driver_source_state(self) -> DriverSourceDriverSnapshot:
        return DriverSourceDriverSnapshot(
            state=DriverSourceLeftState(enabled=True, level=4),
            metadata={"snapshot": "source"},
        )

    @override
    def apply_driver_source_state(
        self,
        patch: DriverSourceDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        self.patch = patch
        return DriverSuccess(None, metadata={"handler": "source"})


class _CompositeDriver(MonitorCompositeDriverAdapter):
    implementation_id = "test.composite"
    implementation_version = "v1"
    instrument_id = "composite"

    def __init__(self, *, monitor: bool) -> None:
        super().__init__(monitor=monitor)
        self.apply_calls: list[MonitorCompositeDriverPatch] = []
        self.monitor_calls = 0

    @override
    def read_monitor_composite_state(self) -> MonitorCompositeDriverSnapshot:
        return MonitorCompositeDriverSnapshot(
            driver_source=DriverSourceLeftState(enabled=True, level=8),
            # Deliberately populated even when the optional interface is disabled:
            # the adapter owns the dynamic interface gate.
            driver_monitor=DriverMonitorState(enabled=True),
            metadata={"snapshot": "composite"},
        )

    @override
    def apply_monitor_composite_state(
        self,
        patch: MonitorCompositeDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        self.apply_calls.append(patch)
        return DriverSuccess(None, metadata={"handler": "composite_apply"})

    @override
    def handle_monitor(self) -> DriverOutcome[DriverMonitorMonitorDriverReadback]:
        self.monitor_calls += 1
        return DriverSuccess(
            DriverMonitorMonitorDriverReadback(
                left=_measurement("V"),
                right=_measurement("A"),
                metadata={"readback": "composite"},
            ),
            metadata={"handler": "composite_collect"},
        )

    def describe(self) -> InstrumentDescription:
        raise NotImplementedError

    def disconnect(self) -> None:
        pass

    def abort(self) -> None:
        pass


def _measurement(unit: str) -> MeasurementScalar:
    return MeasurementScalar.create(
        dtype="float64",
        unit=unit,
        value=1.25,
    )


def _as_instrument_driver(driver: InstrumentDriver) -> InstrumentDriver:
    return driver


def test_component_scalar_operation_preserves_signature_and_metadata() -> None:
    driver = _ComponentDriver()
    width = Quantity(2.5, "ms")

    outcome = driver.invoke(
        DriverOperation(
            target=COMPONENT_OPERATION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE,
            arguments={
                "pulse_count": 3,
                "pulse_width": width,
                "pulse_label": "sync",
            },
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert outcome.value is None
    assert outcome.metadata == {"handler": "component"}
    assert driver.call == (3, width, "sync")


def test_literal_and_payload_operations_only_unwrap_raw_arguments() -> None:
    literal = _LiteralDriver()
    selected = literal.invoke(
        DriverOperation(
            target=LITERAL_OPERATION_SELECT,
            arguments={"mode": "left"},
        )
    )
    assert isinstance(selected, DriverSuccess)
    assert literal.selected == "left"

    rejected = literal.invoke(
        DriverOperation(
            target=LITERAL_OPERATION_SELECT,
            arguments={"mode": "right"},
        )
    )
    assert rejected is literal.rejected

    payload = _PayloadDriver()
    uploaded = payload.invoke(
        DriverOperation(
            target=PAYLOAD_OPERATION_UPLOAD,
            arguments={
                "payload": DriverPayload(
                    schema_id="test.payload/v1",
                    value=b"opaque bytes",
                )
            },
        )
    )
    assert isinstance(uploaded, DriverSuccess)
    assert payload.payload == b"opaque bytes"

    unknown = payload.invoke(
        DriverOperation(
            target=PAYLOAD_OPERATION_UPLOAD,
            arguments={
                "payload": DriverPayload(
                    schema_id="test.payload/v1",
                    value=b"unknown",
                )
            },
        )
    )
    assert unknown is payload.unknown


def test_fixed_acquisition_maps_name_and_preserves_both_metadata_layers() -> None:
    driver = _FixedDriver()

    outcome = driver.collect(
        DriverAcquisition(
            target=DRIVER_FIXED_ACQUISITION_ACQUIRE,
            results=frozenset({DRIVER_FIXED_ACQUISITION_RESPONSE_RESULT}),
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert driver.acquire_calls == 1
    assert set(outcome.value.values) == {DRIVER_FIXED_ACQUISITION_RESPONSE_RESULT}
    assert outcome.value.metadata == {"readback": "fixed"}
    assert outcome.metadata == {"handler": "fixed"}


def test_single_interface_state_snapshot_and_patch_are_typed() -> None:
    driver = _SourceDriver()

    state = driver.read_state()
    assert state.values == {
        DRIVER_SOURCE_MODE: "left",
        DRIVER_SOURCE_ENABLED: True,
        DRIVER_SOURCE_LEFT_LEVEL: 4,
    }
    assert state.metadata == {"snapshot": "source"}

    outcome = driver.apply_state(
        DriverStatePatch(
            values={
                DRIVER_SOURCE_MODE: "right",
                DRIVER_SOURCE_ENABLED: False,
                DRIVER_SOURCE_RIGHT_LEVEL: 9,
            }
        )
    )
    assert isinstance(outcome, DriverSuccess)
    assert outcome.value is None
    assert outcome.metadata == {"handler": "source"}
    assert driver.patch == {
        "mode": "right",
        "enabled": False,
        "right_level": 9,
    }


def test_composite_apply_calls_one_typed_hook_and_dynamic_gate_owns_monitor() -> None:
    enabled = _CompositeDriver(monitor=True)

    outcome = enabled.apply_state(
        DriverStatePatch(
            values={
                DRIVER_SOURCE_ENABLED: False,
                DRIVER_MONITOR_ENABLED: True,
            }
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert outcome.value is None
    assert outcome.metadata == {"handler": "composite_apply"}
    assert len(enabled.apply_calls) == 1
    assert enabled.apply_calls[0].driver_source == {"enabled": False}
    assert enabled.apply_calls[0].driver_monitor == {"enabled": True}
    assert DRIVER_MONITOR_ENABLED in enabled.read_state().values

    disabled = _CompositeDriver(monitor=False)
    assert DRIVER_MONITOR_ENABLED not in disabled.read_state().values
    rejected = disabled.apply_state(
        DriverStatePatch(values={DRIVER_MONITOR_ENABLED: True})
    )
    assert isinstance(rejected, DriverRejected)
    assert rejected.problems[0].code == "instrument_state_not_implemented"
    assert disabled.apply_calls == []


def test_composite_acquisition_projects_requested_results_and_uses_dynamic_gate() -> (
    None
):
    enabled = _CompositeDriver(monitor=True)
    outcome = enabled.collect(
        DriverAcquisition(
            target=DRIVER_MONITOR_ACQUISITION,
            results=frozenset({DRIVER_MONITOR_RIGHT_RESULT}),
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert enabled.monitor_calls == 1
    assert set(outcome.value.values) == {DRIVER_MONITOR_RIGHT_RESULT}
    assert outcome.value.metadata == {"readback": "composite"}
    assert outcome.metadata == {"handler": "composite_collect"}

    disabled = _CompositeDriver(monitor=False)
    rejected = disabled.collect(
        DriverAcquisition(
            target=DRIVER_MONITOR_ACQUISITION,
            results=frozenset({DRIVER_MONITOR_RIGHT_RESULT}),
        )
    )
    assert isinstance(rejected, DriverRejected)
    assert rejected.problems[0].code == "instrument_acquisition_not_implemented"
    assert disabled.monitor_calls == 0


def test_generated_composite_adapter_structurally_satisfies_instrument_driver() -> None:
    driver = _CompositeDriver(monitor=True)

    assert _as_instrument_driver(driver) is driver
