from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Mapping
from typing import Annotated, Protocol, assert_type, cast

from scopecat.api._instruments import (
    InstrumentClientChannel,
    InstrumentRef,
    OperationArgumentValue,
)
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
)
from scopecat.sdk.instruments.declarations import (
    argument,
    compile_interface,
    declared_operation,
    declared_state_assignments,
    instrument_interface,
    operation,
)

from scopecat_instruments import (
    DCSourceClient,
    DCSourceMonitorClient,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepClient,
    NetworkSweepState,
    dc_source,
    network_sweep,
)
from scopecat_instruments.clients import _InstrumentClient
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_START_FREQUENCY,
)


@instrument_interface("test.first_party_typed_operation/v1")
class _SyntheticOperationInterface(Protocol):
    @operation(id="emit_pulse")
    def emit(
        self,
        count: Annotated[int, argument(id="pulse_count")],
        *,
        label: Annotated[str, argument(id="pulse_label")],
    ) -> None: ...


_SYNTHETIC_OPERATION = declared_operation(
    compile_interface(_SyntheticOperationInterface),
    _SyntheticOperationInterface.emit,
)


class _RecordingInvokeChannel:
    def __init__(self) -> None:
        self.receipt = InvokeReceipt(metadata={"test": "typed-operation"})
        self.operation: OperationRef | None = None
        self.arguments: (
            Mapping[
                OperationArgumentRef,
                OperationArgumentValue,
            ]
            | None
        ) = None
        self.instrument_id: str | None = None

    def invoke(
        self,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = None,
        *,
        instrument_id: str,
    ) -> InvokeReceipt:
        self.operation = operation
        self.arguments = arguments
        self.instrument_id = instrument_id
        return self.receipt


class _SyntheticLiveOperationClient(_InstrumentClient):
    def emit(self, count: int, *, label: str) -> InvokeReceipt:
        return self._invoke_declared(
            _SYNTHETIC_OPERATION,
            count,
            label=label,
        )


def test_first_party_factories_retain_static_client_types() -> None:
    source = dc_source("flux-source")
    vna = network_sweep("readout-vna")

    assert_type(source, InstrumentRef[DCSourceClient])
    assert_type(vna, InstrumentRef[NetworkSweepClient])
    assert source.instrument_id == "flux-source"
    assert vna.instrument_id == "readout-vna"
    assert source.requires == (DC_SOURCE,)
    assert vna.requires == (NETWORK_SWEEP,)


def test_live_declared_operation_lowers_arguments_and_returns_receipt() -> None:
    channel = _RecordingInvokeChannel()
    client = _SyntheticLiveOperationClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "pulse-source",
    )

    receipt = assert_type(client.emit(7, label="calibration"), InvokeReceipt)

    assert receipt is channel.receipt
    assert channel.instrument_id == "pulse-source"
    assert channel.operation == _SYNTHETIC_OPERATION.ref
    assert channel.arguments == {
        _SYNTHETIC_OPERATION.ref.argument("pulse_count"): 7,
        _SYNTHETIC_OPERATION.ref.argument("pulse_label"): "calibration",
    }


def test_live_dc_monitor_selection_requires_the_combined_capability() -> None:
    source = dc_source("flux-source", monitor=True)

    assert_type(source, InstrumentRef[DCSourceMonitorClient])
    assert source.requires == (DC_SOURCE, DC_MONITOR)


def test_voltage_state_is_one_complete_mode_transition() -> None:
    state = DCSourceVoltage(
        range=Quantity(1.0, "V"),
        level=Quantity(0.05, "V"),
        output_enabled=True,
    )

    assert declared_state_assignments(state) == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: Quantity(0.05, "V"),
        DC_SOURCE_OUTPUT_ENABLED: True,
    }


def test_sparse_state_omits_unspecified_properties() -> None:
    assert declared_state_assignments(DCSourceState(output_enabled=False)) == {
        DC_SOURCE_OUTPUT_ENABLED: False
    }
    assert declared_state_assignments(
        NetworkSweepState(
            start_frequency=Quantity(4.8, "GHz"),
            points=401,
            s_parameter="S21",
        )
    ) == {
        NETWORK_SWEEP_START_FREQUENCY: Quantity(4.8, "GHz"),
        NETWORK_SWEEP_POINTS: 401,
        NETWORK_SWEEP_S_PARAMETER: "S21",
    }
