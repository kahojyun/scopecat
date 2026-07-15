"""Exact, reusable calibration declarations for logical measurements.

Measurement calibration is deliberately independent from gate calibration.  A
measurement key describes the logical qubit and promised acquisition shape;
operation and result-slot identities belong to an individual circuit occurrence
and are therefore introduced later by selection and lowering.
"""

from __future__ import annotations

from dataclasses import dataclass

from scopecat_quantum._ids import (
    CalibrationId,
    CircuitOperationId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    Play,
    PulseLeaf,
    PulseProgram,
    ReadoutSignal,
    iter_pulse_leaves,
)


@dataclass(frozen=True, slots=True)
class MeasurementCalibrationKey:
    """Reusable logical identity of one single-qubit measurement shape."""

    qubit: QubitId
    acquisition_kind: AcquisitionKind

    @classmethod
    def from_measurement(cls, measurement: Measure) -> MeasurementCalibrationKey:
        """Snapshot the reusable calibration key of one measurement occurrence."""

        return cls(
            qubit=measurement.qubit,
            acquisition_kind=measurement.acquisition_kind,
        )


def _measurement_template_leaves(
    pulse_template: PulseProgram,
    key: MeasurementCalibrationKey,
    *,
    subject: str,
) -> tuple[PulseLeaf, ...]:
    """Validate and expose the measurement-specific refinement contract."""

    slots = pulse_template.acquisition_slots
    if len(slots) != 1:
        msg = f"{subject} pulse template must declare exactly one acquisition slot"
        raise ValueError(msg)
    slot = slots[0]
    if slot.kind is not key.acquisition_kind:
        msg = f"{subject} acquisition slot kind must match its calibration key"
        raise ValueError(msg)
    expected_acquire_signal = AcquireSignal(key.qubit)
    if slot.signal != expected_acquire_signal:
        msg = f"{subject} acquisition slot signal must match its calibration qubit"
        raise ValueError(msg)

    leaves = tuple(iter_pulse_leaves(pulse_template.body))
    event_ids = tuple(leaf.id for leaf in leaves)
    if len(set(event_ids)) != len(event_ids):
        msg = f"{subject} pulse template event ids must be unique"
        raise ValueError(msg)

    acquires = tuple(leaf for leaf in leaves if isinstance(leaf, Acquire))
    if len(acquires) != 1:
        msg = f"{subject} pulse template must contain exactly one Acquire instruction"
        raise ValueError(msg)
    acquire = acquires[0]
    if acquire.slot_id != slot.id:
        msg = f"{subject} Acquire instruction must close its declared acquisition slot"
        raise ValueError(msg)
    if acquire.signal != expected_acquire_signal:
        msg = f"{subject} Acquire signal must match its calibration qubit"
        raise ValueError(msg)

    expected_readout_signal = ReadoutSignal(key.qubit)
    if not any(
        isinstance(leaf, Play) and leaf.signal == expected_readout_signal
        for leaf in leaves
    ):
        msg = f"{subject} pulse template must play its calibration qubit readout signal"
        raise ValueError(msg)
    return leaves


@dataclass(frozen=True, slots=True)
class MeasurementCalibration:
    """One exact measurement calibration with a reusable pulse template."""

    id: CalibrationId
    key: MeasurementCalibrationKey
    pulse_template: PulseProgram

    def __post_init__(self) -> None:
        _measurement_template_leaves(
            self.pulse_template,
            self.key,
            subject="measurement calibration",
        )


@dataclass(frozen=True, slots=True)
class MeasurementCalibrationCatalog:
    """Order-independent collection of measurement calibrations."""

    entries: tuple[MeasurementCalibration, ...]

    def __post_init__(self) -> None:
        entries = self.entries
        calibration_ids = tuple(entry.id for entry in entries)
        if len(set(calibration_ids)) != len(calibration_ids):
            msg = "measurement calibration ids must be unique within a catalog"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda entry: entry.id.value)),
        )


@dataclass(frozen=True, slots=True)
class MeasurementCalibrationBinding:
    """Exact selected pulse template for one logical measurement occurrence."""

    measurement_id: CircuitOperationId
    key: MeasurementCalibrationKey
    calibration_id: CalibrationId
    pulse_template: PulseProgram


__all__ = [
    "MeasurementCalibration",
    "MeasurementCalibrationBinding",
    "MeasurementCalibrationCatalog",
    "MeasurementCalibrationKey",
]
