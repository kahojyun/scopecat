"""Exact, reusable calibration declarations for logical measurements.

Measurement calibration is deliberately independent from gate calibration.  A
measurement key describes the logical qubit and promised acquisition shape;
operation and result-slot identities belong to an individual circuit occurrence
and are therefore introduced later by selection and lowering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Play,
    PulseLeaf,
    PulseProgram,
    ReadoutSignal,
    iter_pulse_leaves,
)


def _runtime_object(value: object) -> object:
    """Erase a public field's static type before checking its runtime shape."""

    return value


def _runtime_tuple(value: object) -> tuple[object, ...] | None:
    return cast("tuple[object, ...]", value) if isinstance(value, tuple) else None


def _is_valid_event_id(value: object) -> bool:
    if not isinstance(value, PulseEventId):
        return False
    try:
        PulseEventId(local_id=value.local_id, scope=value.scope)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _is_valid_acquisition_slot_id(value: object) -> bool:
    if not isinstance(value, AcquisitionSlotId):
        return False
    try:
        AcquisitionSlotId(local_id=value.local_id, scope=value.scope)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _is_valid_program_id(value: object) -> bool:
    if not isinstance(value, PulseProgramId):
        return False
    try:
        PulseProgramId(value.value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class MeasurementCalibrationKey:
    """Reusable logical identity of one single-qubit measurement shape."""

    qubit: QubitId
    acquisition_kind: AcquisitionKind

    def __post_init__(self) -> None:
        if not isinstance(_runtime_object(self.qubit), QubitId):
            msg = "measurement calibration key qubit must be a QubitId"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.acquisition_kind), AcquisitionKind):
            msg = (
                "measurement calibration key acquisition_kind must be an "
                "AcquisitionKind"
            )
            raise ValueError(msg)

    @classmethod
    def from_measurement(cls, measurement: Measure) -> MeasurementCalibrationKey:
        """Snapshot the reusable calibration key of one measurement occurrence."""

        if not isinstance(_runtime_object(measurement), Measure):
            msg = "measurement calibration keys can only be created from a Measure"
            raise TypeError(msg)
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

    if not _is_valid_program_id(_runtime_object(pulse_template.id)):
        msg = f"{subject} pulse template id must be a valid PulseProgramId"
        raise ValueError(msg)

    raw_slots = _runtime_tuple(_runtime_object(pulse_template.acquisition_slots))
    if raw_slots is None or not all(
        isinstance(slot, AcquisitionSlot) for slot in raw_slots
    ):
        msg = f"{subject} acquisition slots must be a tuple of AcquisitionSlot values"
        raise ValueError(msg)
    slots = cast("tuple[AcquisitionSlot, ...]", raw_slots)
    if len(slots) != 1:
        msg = f"{subject} pulse template must declare exactly one acquisition slot"
        raise ValueError(msg)
    slot = slots[0]
    if not _is_valid_acquisition_slot_id(_runtime_object(slot.id)):
        msg = f"{subject} acquisition slot id must be a valid AcquisitionSlotId"
        raise ValueError(msg)
    if _runtime_object(slot.kind) is not key.acquisition_kind:
        msg = f"{subject} acquisition slot kind must match its calibration key"
        raise ValueError(msg)
    expected_acquire_signal = AcquireSignal(key.qubit)
    if _runtime_object(slot.signal) != expected_acquire_signal:
        msg = f"{subject} acquisition slot signal must match its calibration qubit"
        raise ValueError(msg)

    try:
        leaves = tuple(iter_pulse_leaves(pulse_template.body))
    except (AttributeError, TypeError) as error:
        msg = f"{subject} pulse template body must contain pulse instructions"
        raise ValueError(msg) from error

    raw_event_ids = tuple(_runtime_object(leaf.id) for leaf in leaves)
    if not all(_is_valid_event_id(event_id) for event_id in raw_event_ids):
        msg = f"{subject} pulse template event ids must be valid PulseEventId values"
        raise ValueError(msg)
    event_ids = cast("tuple[PulseEventId, ...]", raw_event_ids)
    if len(set(event_ids)) != len(event_ids):
        msg = f"{subject} pulse template event ids must be unique"
        raise ValueError(msg)

    acquires = tuple(leaf for leaf in leaves if isinstance(leaf, Acquire))
    if len(acquires) != 1:
        msg = f"{subject} pulse template must contain exactly one Acquire instruction"
        raise ValueError(msg)
    acquire = acquires[0]
    if _runtime_object(acquire.slot_id) != slot.id:
        msg = f"{subject} Acquire instruction must close its declared acquisition slot"
        raise ValueError(msg)
    if _runtime_object(acquire.signal) != expected_acquire_signal:
        msg = f"{subject} Acquire signal must match its calibration qubit"
        raise ValueError(msg)

    expected_readout_signal = ReadoutSignal(key.qubit)
    if not any(
        isinstance(leaf, Play)
        and _runtime_object(leaf.signal) == expected_readout_signal
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
        if not isinstance(_runtime_object(self.id), CalibrationId):
            msg = "measurement calibration id must be a CalibrationId"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.key), MeasurementCalibrationKey):
            msg = "measurement calibration key must be a MeasurementCalibrationKey"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.pulse_template), PulseProgram):
            msg = "measurement calibrations require a pulse template"
            raise ValueError(msg)
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
        raw_entries = _runtime_tuple(_runtime_object(self.entries))
        if raw_entries is None or not all(
            isinstance(entry, MeasurementCalibration) for entry in raw_entries
        ):
            msg = (
                "measurement calibration catalog entries must be a tuple of "
                "MeasurementCalibration values"
            )
            raise ValueError(msg)
        entries = cast("tuple[MeasurementCalibration, ...]", raw_entries)
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

    def __post_init__(self) -> None:
        if not isinstance(_runtime_object(self.measurement_id), CircuitOperationId):
            msg = (
                "measurement calibration binding measurement_id must be a "
                "CircuitOperationId"
            )
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.key), MeasurementCalibrationKey):
            msg = (
                "measurement calibration binding key must be a "
                "MeasurementCalibrationKey"
            )
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.calibration_id), CalibrationId):
            msg = (
                "measurement calibration binding calibration_id must be a CalibrationId"
            )
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.pulse_template), PulseProgram):
            msg = "measurement calibration binding requires a PulseProgram template"
            raise ValueError(msg)
        _measurement_template_leaves(
            self.pulse_template,
            self.key,
            subject="measurement calibration binding",
        )


__all__ = [
    "MeasurementCalibration",
    "MeasurementCalibrationBinding",
    "MeasurementCalibrationCatalog",
    "MeasurementCalibrationKey",
]
