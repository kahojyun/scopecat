"""Aggregate gate and measurement calibration selection.

Gate and measurement calibrations retain separate typed catalogs and bindings.
The aggregate catalog and selection ensure that one circuit cannot accidentally
prove only one operation family before circuit-to-pulse lowering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from scopecat import Quantity

from scopecat_quantum._ids import (
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.circuits import Measure, VerifiedCircuitProgram
from scopecat_quantum.gates import (
    GateArgument,
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


def _runtime_object(value: object) -> object:
    """Erase a public field's static type before checking its runtime shape."""

    return value


def _runtime_tuple(value: object) -> tuple[object, ...] | None:
    return cast("tuple[object, ...]", value) if isinstance(value, tuple) else None


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _gate_template_leaves(
    pulse_template: PulseProgram,
    *,
    subject: str,
) -> tuple[PulseLeaf, ...]:
    if not isinstance(_runtime_object(pulse_template.id), PulseProgramId):
        msg = f"{subject} pulse template id must be a PulseProgramId"
        raise ValueError(msg)
    try:
        leaves = tuple(iter_pulse_leaves(pulse_template.body))
    except (AttributeError, TypeError) as error:
        msg = f"{subject} pulse template body must contain pulse instructions"
        raise ValueError(msg) from error
    raw_event_ids = tuple(_runtime_object(leaf.id) for leaf in leaves)
    if not all(isinstance(event_id, PulseEventId) for event_id in raw_event_ids):
        msg = f"{subject} pulse template event ids must be PulseEventId values"
        raise ValueError(msg)
    event_ids = cast("tuple[PulseEventId, ...]", raw_event_ids)
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
        argument_id = _runtime_object(self.id)
        if not isinstance(argument_id, str) or not argument_id.strip():
            msg = "calibration argument id must be a non-empty string"
            raise ValueError(msg)
        value = _runtime_object(self.value)
        if isinstance(value, bool):
            msg = "calibration argument value must be a finite gate argument value"
            raise ValueError(msg)
        if isinstance(value, int):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
        elif isinstance(value, Quantity):
            raw_value = _runtime_object(value.value)
            raw_unit = _runtime_object(value.unit)
            if _is_finite_number(raw_value) and isinstance(raw_unit, str):
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
        gate_id = _runtime_object(self.gate_id)
        if not isinstance(gate_id, GateId):
            msg = "calibration key gate_id must be a GateId"
            raise ValueError(msg)
        raw_operands = _runtime_tuple(_runtime_object(self.operands))
        if raw_operands is None or not all(
            isinstance(operand, QubitId) for operand in raw_operands
        ):
            msg = "calibration key operands must be a tuple of QubitId values"
            raise ValueError(msg)
        if not raw_operands:
            msg = "calibration keys require at least one operand"
            raise ValueError(msg)
        if len(set(raw_operands)) != len(raw_operands):
            msg = "calibration key operands must be unique"
            raise ValueError(msg)
        raw_arguments = _runtime_tuple(_runtime_object(self.arguments))
        if raw_arguments is None or not all(
            isinstance(argument, GateCalibrationArgument) for argument in raw_arguments
        ):
            msg = (
                "calibration key arguments must be a tuple of "
                "GateCalibrationArgument values"
            )
            raise ValueError(msg)
        arguments = cast("tuple[GateCalibrationArgument, ...]", raw_arguments)
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
        if not isinstance(_runtime_object(call), GateCall):
            msg = "calibration keys can only be created from a GateCall"
            raise TypeError(msg)
        raw_arguments = _runtime_tuple(_runtime_object(call.arguments))
        if raw_arguments is None or not all(
            isinstance(argument, GateArgument) for argument in raw_arguments
        ):
            msg = "gate call arguments must be a tuple of GateArgument values"
            raise ValueError(msg)
        arguments = cast("tuple[GateArgument, ...]", raw_arguments)
        return cls(
            gate_id=call.gate_id,
            operands=call.qubits,
            arguments=tuple(
                GateCalibrationArgument(id=argument.id, value=argument.value)
                for argument in arguments
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
        if not isinstance(_runtime_object(self.id), CalibrationId):
            msg = "gate calibration id must be a CalibrationId"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.key), GateCalibrationKey):
            msg = "gate calibration key must be a GateCalibrationKey"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.pulse_template), PulseProgram):
            msg = "gate calibrations require a pulse template"
            raise ValueError(msg)
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
        raw_entries = _runtime_tuple(_runtime_object(self.entries))
        if raw_entries is None or not all(
            isinstance(entry, GateCalibration) for entry in raw_entries
        ):
            msg = (
                "calibration catalog entries must be a tuple of GateCalibration values"
            )
            raise ValueError(msg)
        entries = cast("tuple[GateCalibration, ...]", raw_entries)
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

    def __post_init__(self) -> None:
        if not isinstance(_runtime_object(self.call_id), CircuitOperationId):
            msg = "calibration binding call_id must be a CircuitOperationId"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.key), GateCalibrationKey):
            msg = "calibration binding key must be a GateCalibrationKey"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.calibration_id), CalibrationId):
            msg = "calibration binding calibration_id must be a CalibrationId"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.pulse_template), PulseProgram):
            msg = "calibration binding requires a PulseProgram template"
            raise ValueError(msg)
        leaves = _gate_template_leaves(
            self.pulse_template,
            subject="gate calibration binding",
        )
        if self.pulse_template.acquisition_slots or any(
            isinstance(leaf, Acquire) for leaf in leaves
        ):
            msg = (
                "gate calibration bindings cannot reference pulse templates with "
                "acquisition slots or Acquire instructions"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, init=False)
class GateCalibrationSelection:
    """Sealed proof that every gate call has exactly one calibration."""

    _circuit_id: CircuitId
    _gate_call_ids: tuple[CircuitOperationId, ...]
    _bindings: tuple[GateCalibrationBinding, ...]

    def __init__(
        self,
        circuit_id: CircuitId,
        gate_call_ids: tuple[CircuitOperationId, ...],
        bindings: tuple[GateCalibrationBinding, ...],
    ) -> None:
        if not isinstance(_runtime_object(circuit_id), CircuitId):
            msg = "calibration selection circuit_id must be a CircuitId"
            raise ValueError(msg)
        raw_gate_call_ids = _runtime_tuple(_runtime_object(gate_call_ids))
        if raw_gate_call_ids is None or not all(
            isinstance(call_id, CircuitOperationId) for call_id in raw_gate_call_ids
        ):
            msg = (
                "calibration selection gate_call_ids must be a tuple of "
                "CircuitOperationId values"
            )
            raise ValueError(msg)
        raw_bindings = _runtime_tuple(_runtime_object(bindings))
        if raw_bindings is None or not all(
            isinstance(binding, GateCalibrationBinding) for binding in raw_bindings
        ):
            msg = (
                "calibration selection bindings must be a tuple of "
                "GateCalibrationBinding values"
            )
            raise ValueError(msg)
        selected_call_ids = cast("tuple[CircuitOperationId, ...]", raw_gate_call_ids)
        if len(set(selected_call_ids)) != len(selected_call_ids):
            msg = "calibration selection gate_call_ids must be unique"
            raise ValueError(msg)
        selected_bindings = cast("tuple[GateCalibrationBinding, ...]", raw_bindings)
        binding_ids = tuple(binding.call_id for binding in selected_bindings)
        if binding_ids != selected_call_ids:
            msg = "calibration bindings must exactly cover gate calls in program order"
            raise ValueError(msg)
        object.__setattr__(self, "_circuit_id", circuit_id)
        object.__setattr__(self, "_gate_call_ids", selected_call_ids)
        object.__setattr__(self, "_bindings", selected_bindings)

    @property
    def circuit_id(self) -> CircuitId:
        return self._circuit_id

    @property
    def gate_call_ids(self) -> tuple[CircuitOperationId, ...]:
        return self._gate_call_ids

    @property
    def bindings(self) -> tuple[GateCalibrationBinding, ...]:
        return self._bindings

    def binding_for(self, call_id: CircuitOperationId) -> GateCalibrationBinding:
        for binding in self._bindings:
            if binding.call_id == call_id:
                return binding
        msg = f"gate call {call_id.value!r} is not covered by this selection"
        raise KeyError(msg)


def _create_gate_calibration_selection(
    circuit_id: CircuitId,
    gate_call_ids: tuple[CircuitOperationId, ...],
    bindings: tuple[GateCalibrationBinding, ...],
) -> GateCalibrationSelection:
    return GateCalibrationSelection(
        circuit_id,
        gate_call_ids,
        bindings,
    )


@dataclass(frozen=True, slots=True, init=False)
class MeasurementCalibrationSelection:
    """Sealed proof that every logical measurement has one exact calibration."""

    _circuit_id: CircuitId
    _measurement_ids: tuple[CircuitOperationId, ...]
    _bindings: tuple[MeasurementCalibrationBinding, ...]

    def __init__(
        self,
        circuit_id: CircuitId,
        measurement_ids: tuple[CircuitOperationId, ...],
        bindings: tuple[MeasurementCalibrationBinding, ...],
    ) -> None:
        if not isinstance(_runtime_object(circuit_id), CircuitId):
            msg = "measurement calibration selection circuit_id must be a CircuitId"
            raise ValueError(msg)
        raw_measurement_ids = _runtime_tuple(_runtime_object(measurement_ids))
        if raw_measurement_ids is None or not all(
            isinstance(measurement_id, CircuitOperationId)
            for measurement_id in raw_measurement_ids
        ):
            msg = (
                "measurement calibration selection measurement_ids must be a tuple "
                "of CircuitOperationId values"
            )
            raise ValueError(msg)
        selected_measurement_ids = cast(
            "tuple[CircuitOperationId, ...]", raw_measurement_ids
        )
        if len(set(selected_measurement_ids)) != len(selected_measurement_ids):
            msg = "measurement calibration selection measurement_ids must be unique"
            raise ValueError(msg)

        raw_bindings = _runtime_tuple(_runtime_object(bindings))
        if raw_bindings is None or not all(
            isinstance(binding, MeasurementCalibrationBinding)
            for binding in raw_bindings
        ):
            msg = (
                "measurement calibration selection bindings must be a tuple of "
                "MeasurementCalibrationBinding values"
            )
            raise ValueError(msg)
        selected_bindings = cast(
            "tuple[MeasurementCalibrationBinding, ...]", raw_bindings
        )
        binding_ids = tuple(binding.measurement_id for binding in selected_bindings)
        if binding_ids != selected_measurement_ids:
            msg = (
                "measurement calibration bindings must exactly cover measurements "
                "in program order"
            )
            raise ValueError(msg)

        object.__setattr__(self, "_circuit_id", circuit_id)
        object.__setattr__(self, "_measurement_ids", selected_measurement_ids)
        object.__setattr__(self, "_bindings", selected_bindings)

    @property
    def circuit_id(self) -> CircuitId:
        return self._circuit_id

    @property
    def measurement_ids(self) -> tuple[CircuitOperationId, ...]:
        return self._measurement_ids

    @property
    def bindings(self) -> tuple[MeasurementCalibrationBinding, ...]:
        return self._bindings

    def binding_for(
        self,
        measurement_id: CircuitOperationId,
    ) -> MeasurementCalibrationBinding:
        for binding in self._bindings:
            if binding.measurement_id == measurement_id:
                return binding
        msg = f"measurement {measurement_id.value!r} is not covered by this selection"
        raise KeyError(msg)


def _create_measurement_calibration_selection(
    circuit_id: CircuitId,
    measurement_ids: tuple[CircuitOperationId, ...],
    bindings: tuple[MeasurementCalibrationBinding, ...],
) -> MeasurementCalibrationSelection:
    return MeasurementCalibrationSelection(
        circuit_id,
        measurement_ids,
        bindings,
    )


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
        if not isinstance(_runtime_object(self.gates), GateCalibrationCatalog):
            msg = "calibration catalog gates must be a GateCalibrationCatalog"
            raise ValueError(msg)
        if not isinstance(
            _runtime_object(self.measurements),
            MeasurementCalibrationCatalog,
        ):
            msg = (
                "calibration catalog measurements must be a "
                "MeasurementCalibrationCatalog"
            )
            raise ValueError(msg)
        calibration_ids = tuple(
            entry.id for entry in (*self.gates.entries, *self.measurements.entries)
        )
        if len(set(calibration_ids)) != len(calibration_ids):
            msg = "calibration ids must be unique across gate and measurement catalogs"
            raise ValueError(msg)


type CalibrationKey = GateCalibrationKey | MeasurementCalibrationKey
type CalibrationBinding = GateCalibrationBinding | MeasurementCalibrationBinding


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
        if not isinstance(_runtime_object(self.code), CalibrationSelectionIssueCode):
            msg = "calibration selection issue code is invalid"
            raise ValueError(msg)
        if not isinstance(_runtime_object(self.operation_id), CircuitOperationId):
            msg = (
                "calibration selection issue operation_id must be a CircuitOperationId"
            )
            raise ValueError(msg)
        if not isinstance(
            _runtime_object(self.key),
            GateCalibrationKey | MeasurementCalibrationKey,
        ):
            msg = "calibration selection issue key is invalid"
            raise ValueError(msg)
        raw_matching_ids = _runtime_tuple(
            _runtime_object(self.matching_calibration_ids)
        )
        if raw_matching_ids is None or not all(
            isinstance(calibration_id, CalibrationId)
            for calibration_id in raw_matching_ids
        ):
            msg = (
                "calibration selection issue matches must be a tuple of CalibrationId "
                "values"
            )
            raise ValueError(msg)
        matching_ids = cast("tuple[CalibrationId, ...]", raw_matching_ids)
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
        message = _runtime_object(self.message)
        if not isinstance(message, str) or not message.strip():
            msg = "calibration selection issue message must be non-empty"
            raise ValueError(msg)


class CalibrationSelectionError(ValueError):
    """Aggregate exact-coverage failure, independent of catalog order."""

    def __init__(self, issues: tuple[CalibrationSelectionIssue, ...]) -> None:
        raw_issues = _runtime_tuple(_runtime_object(issues))
        if raw_issues is None or not all(
            isinstance(issue, CalibrationSelectionIssue) for issue in raw_issues
        ):
            msg = (
                "calibration selection errors require a tuple of "
                "CalibrationSelectionIssue values"
            )
            raise ValueError(msg)
        selected_issues = cast("tuple[CalibrationSelectionIssue, ...]", raw_issues)
        if not selected_issues:
            msg = "calibration selection errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                selected_issues,
                key=lambda issue: (
                    issue.operation_id.value,
                    issue.code.value,
                    tuple(item.value for item in issue.matching_calibration_ids),
                ),
            )
        )
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True, init=False)
class CalibrationSelection:
    """Sealed proof that every circuit operation has one typed calibration."""

    _circuit_id: CircuitId
    _operation_ids: tuple[CircuitOperationId, ...]
    _gates: GateCalibrationSelection
    _measurements: MeasurementCalibrationSelection

    def __init__(
        self,
        circuit_id: CircuitId,
        operation_ids: tuple[CircuitOperationId, ...],
        gates: GateCalibrationSelection,
        measurements: MeasurementCalibrationSelection,
    ) -> None:
        if not isinstance(_runtime_object(circuit_id), CircuitId):
            msg = "calibration selection circuit_id must be a CircuitId"
            raise ValueError(msg)
        raw_operation_ids = _runtime_tuple(_runtime_object(operation_ids))
        if raw_operation_ids is None or not all(
            isinstance(operation_id, CircuitOperationId)
            for operation_id in raw_operation_ids
        ):
            msg = (
                "calibration selection operation_ids must be a tuple of "
                "CircuitOperationId values"
            )
            raise ValueError(msg)
        if not isinstance(_runtime_object(gates), GateCalibrationSelection):
            msg = "calibration selection gates must be a GateCalibrationSelection"
            raise ValueError(msg)
        if not isinstance(
            _runtime_object(measurements),
            MeasurementCalibrationSelection,
        ):
            msg = (
                "calibration selection measurements must be a "
                "MeasurementCalibrationSelection"
            )
            raise ValueError(msg)
        if gates.circuit_id != circuit_id or measurements.circuit_id != circuit_id:
            msg = "calibration sub-selections must belong to the same circuit"
            raise ValueError(msg)
        selected_operation_ids = cast(
            "tuple[CircuitOperationId, ...]",
            raw_operation_ids,
        )
        if len(set(selected_operation_ids)) != len(selected_operation_ids):
            msg = "calibration selection operation_ids must be unique"
            raise ValueError(msg)
        covered_ids = (*gates.gate_call_ids, *measurements.measurement_ids)
        if len(set(covered_ids)) != len(covered_ids) or set(covered_ids) != set(
            selected_operation_ids
        ):
            msg = "calibration sub-selections must exactly cover circuit operations"
            raise ValueError(msg)
        object.__setattr__(self, "_circuit_id", circuit_id)
        object.__setattr__(self, "_operation_ids", selected_operation_ids)
        object.__setattr__(self, "_gates", gates)
        object.__setattr__(self, "_measurements", measurements)

    @property
    def circuit_id(self) -> CircuitId:
        return self._circuit_id

    @property
    def operation_ids(self) -> tuple[CircuitOperationId, ...]:
        return self._operation_ids

    @property
    def gates(self) -> GateCalibrationSelection:
        return self._gates

    @property
    def measurements(self) -> MeasurementCalibrationSelection:
        return self._measurements

    def binding_for(self, operation_id: CircuitOperationId) -> CalibrationBinding:
        try:
            return self._gates.binding_for(operation_id)
        except KeyError:
            pass
        try:
            return self._measurements.binding_for(operation_id)
        except KeyError:
            msg = f"operation {operation_id.value!r} is not covered by this selection"
            raise KeyError(msg) from None


def select_calibrations(
    program: VerifiedCircuitProgram,
    catalog: CalibrationCatalog,
) -> CalibrationSelection:
    """Select one exact typed calibration per operation or aggregate failures."""

    if not isinstance(_runtime_object(program), VerifiedCircuitProgram):
        msg = "calibration selection requires a VerifiedCircuitProgram"
        raise TypeError(msg)
    if not isinstance(_runtime_object(catalog), CalibrationCatalog):
        msg = "calibration selection requires a CalibrationCatalog"
        raise TypeError(msg)

    gate_entries_by_key: dict[GateCalibrationKey, list[GateCalibration]] = {}
    for entry in catalog.gates.entries:
        gate_entries_by_key.setdefault(entry.key, []).append(entry)
    measurement_entries_by_key: dict[
        MeasurementCalibrationKey,
        list[MeasurementCalibration],
    ] = {}
    for entry in catalog.measurements.entries:
        measurement_entries_by_key.setdefault(entry.key, []).append(entry)

    gate_bindings: list[GateCalibrationBinding] = []
    measurement_bindings: list[MeasurementCalibrationBinding] = []
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
            assert isinstance(operation, Measure)
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
                assert isinstance(key, GateCalibrationKey)
                assert isinstance(selected, GateCalibration)
                gate_bindings.append(
                    GateCalibrationBinding(
                        call_id=operation.id,
                        key=key,
                        calibration_id=selected.id,
                        pulse_template=selected.pulse_template,
                    )
                )
            else:
                assert isinstance(key, MeasurementCalibrationKey)
                assert isinstance(selected, MeasurementCalibration)
                measurement_bindings.append(
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
    gate_call_ids = tuple(
        operation.id
        for operation in program.operations
        if isinstance(operation, GateCall)
    )
    measurement_ids = tuple(
        operation.id
        for operation in program.operations
        if isinstance(operation, Measure)
    )
    gates = _create_gate_calibration_selection(
        circuit_id,
        gate_call_ids,
        tuple(gate_bindings),
    )
    measurements = _create_measurement_calibration_selection(
        circuit_id,
        measurement_ids,
        tuple(measurement_bindings),
    )
    return CalibrationSelection(
        circuit_id,
        tuple(operation.id for operation in program.operations),
        gates,
        measurements,
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
