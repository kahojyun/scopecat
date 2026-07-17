"""Aggregate gate and measurement calibration selection.

Gate and measurement calibrations retain separate typed catalogs and bindings.
The aggregate catalog and selection ensure that one circuit cannot accidentally
prove only one operation family before circuit-to-pulse lowering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from scopecat_quantum._ids import (
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    GateId,
    QubitId,
)
from scopecat_quantum.circuits import Measure, VerifiedCircuitProgram
from scopecat_quantum.gates import (
    GateArgumentValue,
    GateCall,
    canonical_angle_value,
)
from scopecat_quantum.measurement_calibrations import (
    MeasurementCalibration,
    MeasurementCalibrationBinding,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
)
from scopecat_quantum.pulses import (
    Acquire,
    PulseLeaf,
    PulseProgram,
    iter_pulse_leaves,
)


def _gate_template_leaves(
    pulse_template: PulseProgram,
    *,
    subject: str,
) -> tuple[PulseLeaf, ...]:
    leaves = tuple(iter_pulse_leaves(pulse_template.body))
    event_ids = tuple(leaf.id for leaf in leaves)
    if len(set(event_ids)) != len(event_ids):
        msg = f"{subject} pulse template event ids must be unique"
        raise ValueError(msg)
    return leaves


@dataclass(frozen=True, slots=True)
class GateCalibrationArgument:
    """A snapshotted, named argument in an exact calibration key."""

    id: str
    value: GateArgumentValue

    def __post_init__(self) -> None:
        if not self.id.strip():
            msg = "calibration argument id must be a non-empty string"
            raise ValueError(msg)
        value = self.value
        if isinstance(value, bool):
            msg = "calibration argument value must be a finite gate argument value"
            raise ValueError(msg)
        if isinstance(value, int):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
        else:
            if math.isfinite(value.value):
                try:
                    canonical = canonical_angle_value(value)
                except ValueError:
                    pass
                else:
                    object.__setattr__(self, "value", canonical)
                    return
        msg = "calibration argument value must be a finite gate argument value"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GateCalibrationKey:
    """Exact data-only identity of a gate call requiring calibration."""

    gate_id: GateId
    operands: tuple[QubitId, ...]
    arguments: tuple[GateCalibrationArgument, ...] = ()

    def __post_init__(self) -> None:
        if not self.operands:
            msg = "calibration keys require at least one operand"
            raise ValueError(msg)
        if len(set(self.operands)) != len(self.operands):
            msg = "calibration key operands must be unique"
            raise ValueError(msg)
        arguments = self.arguments
        argument_ids = tuple(argument.id for argument in arguments)
        if len(set(argument_ids)) != len(argument_ids):
            msg = "calibration key argument ids must be unique"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "arguments",
            tuple(sorted(arguments, key=lambda argument: argument.id)),
        )

    @classmethod
    def from_call(cls, call: GateCall) -> GateCalibrationKey:
        return cls(
            gate_id=call.gate_id,
            operands=call.qubits,
            arguments=tuple(
                GateCalibrationArgument(id=argument.id, value=argument.value)
                for argument in call.arguments
            ),
        )


@dataclass(frozen=True, slots=True)
class GateCalibration:
    """One exact gate calibration referring to a reusable pulse template.

    The template contains template-relative event identities. Gate-to-pulse
    lowering hygienically prefixes those identities for every call; it never
    concatenates this object as an already-instantiated program.
    """

    id: CalibrationId
    key: GateCalibrationKey
    pulse_template: PulseProgram

    def __post_init__(self) -> None:
        leaves = _gate_template_leaves(
            self.pulse_template,
            subject="gate calibration",
        )
        if self.pulse_template.acquisition_slots or any(
            isinstance(leaf, Acquire) for leaf in leaves
        ):
            msg = (
                "gate calibration pulse templates cannot declare acquisition slots "
                "or contain Acquire instructions"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GateCalibrationCatalog:
    """Order-independent collection of exact gate calibrations."""

    entries: tuple[GateCalibration, ...]

    def __post_init__(self) -> None:
        entries = self.entries
        calibration_ids = tuple(entry.id for entry in entries)
        if len(set(calibration_ids)) != len(calibration_ids):
            msg = "calibration ids must be unique within a catalog"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda entry: entry.id.value)),
        )


@dataclass(frozen=True, slots=True)
class GateCalibrationBinding:
    """Exact selected pulse template for one gate invocation.

    ``pulse_template`` still carries calibration-local identities. The lowerer
    consuming this binding must instantiate it into a fresh hygienic scope.
    """

    call_id: CircuitOperationId
    key: GateCalibrationKey
    calibration_id: CalibrationId
    pulse_template: PulseProgram


@dataclass(frozen=True, slots=True)
class GateCalibrationSelection:
    """Selected calibration bindings for the gate calls in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[GateCalibrationBinding, ...]

    @property
    def gate_call_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(binding.call_id for binding in self.bindings)

    def binding_for(self, call_id: CircuitOperationId) -> GateCalibrationBinding:
        for binding in self.bindings:
            if binding.call_id == call_id:
                return binding
        msg = f"gate call {call_id.value!r} is not covered by this selection"
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementCalibrationSelection:
    """Selected calibration bindings for the measurements in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[MeasurementCalibrationBinding, ...]

    @property
    def measurement_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(binding.measurement_id for binding in self.bindings)

    def binding_for(
        self,
        measurement_id: CircuitOperationId,
    ) -> MeasurementCalibrationBinding:
        for binding in self.bindings:
            if binding.measurement_id == measurement_id:
                return binding
        msg = f"measurement {measurement_id.value!r} is not covered by this selection"
        raise KeyError(msg)


def _empty_gate_catalog() -> GateCalibrationCatalog:
    return GateCalibrationCatalog(())


def _empty_measurement_catalog() -> MeasurementCalibrationCatalog:
    return MeasurementCalibrationCatalog(())


@dataclass(frozen=True, slots=True)
class CalibrationCatalog:
    """Complete typed gate and measurement calibration catalog."""

    gates: GateCalibrationCatalog = field(default_factory=_empty_gate_catalog)
    measurements: MeasurementCalibrationCatalog = field(
        default_factory=_empty_measurement_catalog
    )

    def __post_init__(self) -> None:
        calibration_ids = tuple(
            entry.id for entry in (*self.gates.entries, *self.measurements.entries)
        )
        if len(set(calibration_ids)) != len(calibration_ids):
            msg = "calibration ids must be unique across gate and measurement catalogs"
            raise ValueError(msg)


type CalibrationKey = GateCalibrationKey | MeasurementCalibrationKey
type CalibrationBinding = GateCalibrationBinding | MeasurementCalibrationBinding


def _binding_operation_id(binding: CalibrationBinding) -> CircuitOperationId:
    if isinstance(binding, GateCalibrationBinding):
        return binding.call_id
    return binding.measurement_id


class CalibrationSelectionIssueCode(StrEnum):
    """Stable kinds of exact calibration selection failure."""

    MISSING = "calibration_missing"
    AMBIGUOUS = "calibration_ambiguous"


@dataclass(frozen=True, slots=True)
class CalibrationSelectionIssue:
    """One operation-specific calibration coverage problem."""

    code: CalibrationSelectionIssueCode
    operation_id: CircuitOperationId
    key: CalibrationKey
    matching_calibration_ids: tuple[CalibrationId, ...]
    message: str

    def __post_init__(self) -> None:
        matching_ids = self.matching_calibration_ids
        if len(set(matching_ids)) != len(matching_ids):
            msg = "calibration selection issue matching ids must be unique"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "matching_calibration_ids",
            tuple(sorted(matching_ids, key=lambda item: item.value)),
        )
        if self.code is CalibrationSelectionIssueCode.MISSING and matching_ids:
            msg = "missing calibration issues cannot contain matching ids"
            raise ValueError(msg)
        if (
            self.code is CalibrationSelectionIssueCode.AMBIGUOUS
            and len(matching_ids) < 2
        ):
            msg = "ambiguous calibration issues require at least two matching ids"
            raise ValueError(msg)
        if not self.message.strip():
            msg = "calibration selection issue message must be non-empty"
            raise ValueError(msg)


class CalibrationSelectionError(ValueError):
    """Aggregate exact-coverage failure, independent of catalog order."""

    def __init__(self, issues: tuple[CalibrationSelectionIssue, ...]) -> None:
        if not issues:
            msg = "calibration selection errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                issues,
                key=lambda issue: (
                    issue.operation_id.value,
                    issue.code.value,
                    tuple(item.value for item in issue.matching_calibration_ids),
                ),
            )
        )
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    """Typed calibration selection for every operation in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[CalibrationBinding, ...]

    @property
    def operation_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(_binding_operation_id(binding) for binding in self.bindings)

    @property
    def gates(self) -> GateCalibrationSelection:
        return GateCalibrationSelection(
            self.circuit_id,
            tuple(
                binding
                for binding in self.bindings
                if isinstance(binding, GateCalibrationBinding)
            ),
        )

    @property
    def measurements(self) -> MeasurementCalibrationSelection:
        return MeasurementCalibrationSelection(
            self.circuit_id,
            tuple(
                binding
                for binding in self.bindings
                if isinstance(binding, MeasurementCalibrationBinding)
            ),
        )

    def binding_for(self, operation_id: CircuitOperationId) -> CalibrationBinding:
        for binding in self.bindings:
            if _binding_operation_id(binding) == operation_id:
                return binding
        msg = f"operation {operation_id.value!r} is not covered by this selection"
        raise KeyError(msg)


def select_calibrations(
    program: VerifiedCircuitProgram,
    catalog: CalibrationCatalog,
) -> CalibrationSelection:
    """Select one exact typed calibration per operation or aggregate failures."""

    gate_entries_by_key: dict[GateCalibrationKey, list[GateCalibration]] = {}
    for entry in catalog.gates.entries:
        gate_entries_by_key.setdefault(entry.key, []).append(entry)
    measurement_entries_by_key: dict[
        MeasurementCalibrationKey,
        list[MeasurementCalibration],
    ] = {}
    for entry in catalog.measurements.entries:
        measurement_entries_by_key.setdefault(entry.key, []).append(entry)

    bindings: list[CalibrationBinding] = []
    issues: list[CalibrationSelectionIssue] = []
    for operation in program.operations:
        if isinstance(operation, GateCall):
            key: CalibrationKey = GateCalibrationKey.from_call(operation)
            matches: tuple[GateCalibration | MeasurementCalibration, ...] = tuple(
                sorted(
                    gate_entries_by_key.get(key, ()),
                    key=lambda entry: entry.id.value,
                )
            )
        else:
            assert isinstance(operation, Measure)  # noqa: S101
            key = MeasurementCalibrationKey.from_measurement(operation)
            matches = tuple(
                sorted(
                    measurement_entries_by_key.get(key, ()),
                    key=lambda entry: entry.id.value,
                )
            )
        if len(matches) == 1:
            selected = matches[0]
            if isinstance(operation, GateCall):
                assert isinstance(key, GateCalibrationKey)  # noqa: S101
                assert isinstance(selected, GateCalibration)  # noqa: S101
                bindings.append(
                    GateCalibrationBinding(
                        call_id=operation.id,
                        key=key,
                        calibration_id=selected.id,
                        pulse_template=selected.pulse_template,
                    )
                )
            else:
                assert isinstance(key, MeasurementCalibrationKey)  # noqa: S101
                assert isinstance(selected, MeasurementCalibration)  # noqa: S101
                bindings.append(
                    MeasurementCalibrationBinding(
                        measurement_id=operation.id,
                        key=key,
                        calibration_id=selected.id,
                        pulse_template=selected.pulse_template,
                    )
                )
            continue

        code = (
            CalibrationSelectionIssueCode.MISSING
            if not matches
            else CalibrationSelectionIssueCode.AMBIGUOUS
        )
        matching_ids = tuple(entry.id for entry in matches)
        message = (
            f"operation {operation.id.value!r} has no exact calibration"
            if not matches
            else (
                f"operation {operation.id.value!r} has multiple exact calibrations: "
                + ", ".join(repr(item.value) for item in matching_ids)
            )
        )
        issues.append(
            CalibrationSelectionIssue(
                code=code,
                operation_id=operation.id,
                key=key,
                matching_calibration_ids=matching_ids,
                message=message,
            )
        )

    if issues:
        raise CalibrationSelectionError(tuple(issues))

    circuit_id = program.program.id
    return CalibrationSelection(
        circuit_id,
        tuple(bindings),
    )


__all__ = [
    "CalibrationBinding",
    "CalibrationCatalog",
    "CalibrationKey",
    "CalibrationSelection",
    "CalibrationSelectionError",
    "CalibrationSelectionIssue",
    "CalibrationSelectionIssueCode",
    "GateCalibration",
    "GateCalibrationArgument",
    "GateCalibrationBinding",
    "GateCalibrationCatalog",
    "GateCalibrationKey",
    "GateCalibrationSelection",
    "MeasurementCalibration",
    "MeasurementCalibrationBinding",
    "MeasurementCalibrationCatalog",
    "MeasurementCalibrationKey",
    "MeasurementCalibrationSelection",
    "select_calibrations",
]
