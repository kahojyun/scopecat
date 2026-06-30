"""Deterministic response functions driven by virtual-device state."""

from __future__ import annotations

from scopecat.instruments import NativeDriverDiagnostic, NativeMeasurementContext
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementSink

from quantum_lab_demo.readout.responses import (
    ReadoutIQResponseModel,
    ReadoutResponseModel,
    ReadoutSettings,
    _record_iq_shot,
    _record_raw_measurement,
)
from quantum_lab_demo.virtual_lab.devices import VirtualDevice
from quantum_lab_demo.virtual_lab.models import VirtualResponseProfile


def readout_response_model(profile: VirtualResponseProfile) -> ReadoutResponseModel:
    if profile.kind != "readout_frequency_response":
        raise NativeDriverDiagnostic(
            severity="error",
            code="virtual_lab_response_kind_mismatch",
            message=(
                "readout frequency response requires kind=readout_frequency_response"
            ),
            path="response_models.kind",
        )
    return ReadoutResponseModel.model_validate(profile.parameters)


def readout_iq_response_model(
    profile: VirtualResponseProfile,
) -> ReadoutIQResponseModel:
    if profile.kind != "readout_iq_response":
        raise NativeDriverDiagnostic(
            severity="error",
            code="virtual_lab_response_kind_mismatch",
            message="readout IQ response requires kind=readout_iq_response",
            path="response_models.kind",
        )
    return ReadoutIQResponseModel.model_validate(profile.parameters)


def record_readout_frequency_measurement(
    *,
    sink: MeasurementSink,
    context: NativeMeasurementContext,
    readout: VirtualDevice,
    flux_bias: VirtualDevice,
    response_model: ReadoutResponseModel,
    instrument_id: str,
) -> None:
    if context.record != "point":
        raise NativeDriverDiagnostic(
            severity="error",
            code="quantum_native_readout_frr_granularity_unsupported",
            message="readout frequency native stack requires point records",
            path="acquisition.record",
        )
    _record_raw_measurement(
        sink=sink,
        point=context.point,
        settings=_readout_settings(readout=readout, flux_bias=flux_bias),
        response_model=response_model,
        producer_id=instrument_id,
        producer_kind="instrument",
    )


def record_readout_iq_measurements(
    *,
    sink: MeasurementSink,
    context: NativeMeasurementContext,
    readout: VirtualDevice,
    response_model: ReadoutIQResponseModel,
    instrument_id: str,
) -> None:
    if context.record != "shot":
        raise NativeDriverDiagnostic(
            severity="error",
            code="quantum_native_readout_iq_granularity_unsupported",
            message="readout IQ native stack requires shot records",
            path="acquisition.record",
        )
    readout.measurement_metadata()
    for shot_index in range(context.records_for_point):
        _record_iq_shot(
            sink=sink,
            point_index=context.record_index_offset + shot_index,
            shot_index=shot_index,
            response_model=response_model,
            producer_id=instrument_id,
            producer_kind="instrument",
        )


def record_sample_measurement(
    *,
    sink: MeasurementSink,
    context: NativeMeasurementContext,
    readout: VirtualDevice,
    implementation_id: str,
) -> None:
    schema = context.expected_schema
    if schema is None:
        return
    observables = {
        variable.id: Quantity(
            value=_observable_value(
                point_index=context.point_index,
                point_count=context.point_count,
                variable_index=variable_index,
            ),
            unit=variable.unit or "ratio",
        )
        for variable_index, variable in enumerate(schema.variables)
        if variable.role == "observable"
    }
    sink.record(
        point_index=context.point_index,
        coordinates=context.coordinates,
        observables=observables,
        metadata={
            "instrument": readout.id,
            "implementation": implementation_id,
            "virtual_lab": True,
            **readout.measurement_metadata(),
        },
    )


def _readout_settings(
    *, readout: VirtualDevice, flux_bias: VirtualDevice
) -> ReadoutSettings:
    return ReadoutSettings(
        readout_frequency_ghz=_frequency_to_ghz(
            _quantity(readout, "readout_pulse", "frequency", 5.95, "GHz")
        ),
        readout_power_dbm=_power_to_dbm(
            _quantity(readout, "readout_pulse", "power", -27.0, "dBm")
        ),
        demod_frequency_mhz=_frequency_to_mhz(
            _quantity(readout, "demodulate_iq", "demod_frequency", 100.0, "MHz")
        ),
        start_delay_ns=_time_to_ns(
            _quantity(readout, "capture_dataset", "start_delay", 240.0, "ns")
        ),
        phase_offset_rad=_phase_to_rad(
            _quantity(readout, "readout_pulse", "phase", 0.0, "rad")
        ),
        reps=int(
            _quantity(readout, "capture_dataset", "repetitions", 600.0, "count").value
        ),
        z_offset=_quantity(flux_bias, "set_offset", "offset", 0.0, "arb").value,
    )


def _quantity(
    device: VirtualDevice,
    capability_id: str,
    field_path: str,
    default_value: float,
    default_unit: str,
) -> Quantity:
    return device.quantity(capability_id, field_path) or Quantity(
        value=default_value,
        unit=default_unit,
    )


def _frequency_to_ghz(quantity: Quantity) -> float:
    if quantity.unit == "GHz":
        return quantity.value
    if quantity.unit == "MHz":
        return quantity.value / 1000
    if quantity.unit == "kHz":
        return quantity.value / 1_000_000
    if quantity.unit == "Hz":
        return quantity.value / 1_000_000_000
    raise NativeDriverDiagnostic(
        severity="error",
        code="virtual_lab_unsupported_frequency_unit",
        message=f"unsupported frequency unit: {quantity.unit}",
        path="state.quantity.unit",
    )


def _frequency_to_mhz(quantity: Quantity) -> float:
    if quantity.unit == "GHz":
        return quantity.value * 1000
    if quantity.unit == "MHz":
        return quantity.value
    if quantity.unit == "kHz":
        return quantity.value / 1000
    if quantity.unit == "Hz":
        return quantity.value / 1_000_000
    raise NativeDriverDiagnostic(
        severity="error",
        code="virtual_lab_unsupported_frequency_unit",
        message=f"unsupported frequency unit: {quantity.unit}",
        path="state.quantity.unit",
    )


def _time_to_ns(quantity: Quantity) -> float:
    if quantity.unit == "s":
        return quantity.value * 1_000_000_000
    if quantity.unit == "ms":
        return quantity.value * 1_000_000
    if quantity.unit == "us":
        return quantity.value * 1000
    if quantity.unit == "ns":
        return quantity.value
    raise NativeDriverDiagnostic(
        severity="error",
        code="virtual_lab_unsupported_time_unit",
        message=f"unsupported time unit: {quantity.unit}",
        path="state.quantity.unit",
    )


def _power_to_dbm(quantity: Quantity) -> float:
    if quantity.unit != "dBm":
        raise NativeDriverDiagnostic(
            severity="error",
            code="virtual_lab_unsupported_power_unit",
            message=f"unsupported power unit: {quantity.unit}",
            path="state.quantity.unit",
        )
    return quantity.value


def _phase_to_rad(quantity: Quantity) -> float:
    if quantity.unit == "rad":
        return quantity.value
    if quantity.unit == "deg":
        return quantity.value * 3.141592653589793 / 180
    raise NativeDriverDiagnostic(
        severity="error",
        code="virtual_lab_unsupported_phase_unit",
        message=f"unsupported phase unit: {quantity.unit}",
        path="state.quantity.unit",
    )


def _observable_value(
    *,
    point_index: int,
    point_count: int,
    variable_index: int,
) -> float:
    normalized = (point_index + 1) / (point_count + 1)
    return round(normalized + variable_index * 0.01, 12)


__all__ = [
    "readout_iq_response_model",
    "readout_response_model",
    "record_readout_frequency_measurement",
    "record_readout_iq_measurements",
    "record_sample_measurement",
]
