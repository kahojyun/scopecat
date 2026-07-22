"""Resolve logical operations to point-effective pulse implementations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash

from scopecat_quantum._ids import (
    CircuitId,
    CircuitOperationId,
    CouplerId,
    GateId,
    PulseImplementationId,
    QubitId,
)
from scopecat_quantum.circuits import Measure, VerifiedCircuitProgram
from scopecat_quantum.gates import (
    GateArgumentValue,
    GateCall,
    canonical_angle_value,
)
from scopecat_quantum.measurement_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationBinding,
    MeasurementPulseImplementationKey,
)
from scopecat_quantum.pulses import (
    Acquire,
    PulseLeaf,
    PulseProgram,
    iter_pulse_leaves,
    pulse_leaf_owners,
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
class GatePulseImplementationArgument:
    """A snapshotted, named argument in an exact implementation key."""

    id: str
    value: GateArgumentValue

    def __post_init__(self) -> None:
        if not self.id.strip():
            msg = "implementation argument id must be a non-empty string"
            raise ValueError(msg)
        value = self.value
        if isinstance(value, bool):
            msg = "implementation argument value must be finite"
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
        msg = "implementation argument value must be finite"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GatePulseImplementationKey:
    """Exact data-only identity of a logical gate implementation."""

    gate_id: GateId
    operands: tuple[QubitId, ...]
    arguments: tuple[GatePulseImplementationArgument, ...] = ()

    def __post_init__(self) -> None:
        if not self.operands:
            msg = "gate implementation keys require at least one operand"
            raise ValueError(msg)
        if len(set(self.operands)) != len(self.operands):
            msg = "gate implementation key operands must be unique"
            raise ValueError(msg)
        arguments = self.arguments
        argument_ids = tuple(argument.id for argument in arguments)
        if len(set(argument_ids)) != len(argument_ids):
            msg = "gate implementation key argument ids must be unique"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "arguments",
            tuple(sorted(arguments, key=lambda argument: argument.id)),
        )

    @classmethod
    def from_call(cls, call: GateCall) -> GatePulseImplementationKey:
        return cls(
            gate_id=call.gate_id,
            operands=call.qubits,
            arguments=tuple(
                GatePulseImplementationArgument(id=argument.id, value=argument.value)
                for argument in call.arguments
            ),
        )


@dataclass(frozen=True, slots=True)
class GatePulseImplementation:
    """One resolved logical gate implementation with a reusable pulse template.

    The template contains template-relative event identities. Gate-to-pulse
    lowering hygienically prefixes those identities for every call; it never
    concatenates this object as an already-instantiated program.
    """

    id: PulseImplementationId
    key: GatePulseImplementationKey
    pulse_template: PulseProgram
    resources: tuple[CouplerId, ...] = ()

    def __post_init__(self) -> None:
        resources = tuple(self.resources)
        if len(set(resources)) != len(resources):
            msg = "gate implementation resources must be unique"
            raise ValueError(msg)
        leaves = _gate_template_leaves(
            self.pulse_template,
            subject="gate implementation",
        )
        if self.pulse_template.acquisition_slots or any(
            isinstance(leaf, Acquire) for leaf in leaves
        ):
            msg = (
                "gate implementation pulse templates cannot declare acquisition slots "
                "or contain Acquire instructions"
            )
            raise ValueError(msg)
        owners = set(pulse_leaf_owners(self.pulse_template.body))
        allowed_owners = {*self.key.operands, *resources}
        foreign_owners = owners - allowed_owners
        if foreign_owners:
            rendered = ", ".join(
                repr(owner.value)
                for owner in sorted(foreign_owners, key=lambda item: item.value)
            )
            msg = f"gate implementation contains unauthorized signal owners: {rendered}"
            raise ValueError(msg)
        used_resources = {owner for owner in owners if isinstance(owner, CouplerId)}
        unused_resources = set(resources) - used_resources
        if unused_resources:
            rendered = ", ".join(
                repr(owner.value)
                for owner in sorted(unused_resources, key=lambda item: item.value)
            )
            msg = f"gate implementation declares unused coupler resources: {rendered}"
            raise ValueError(msg)
        object.__setattr__(self, "resources", resources)

    @property
    def fingerprint(self) -> str:
        """Identify the exact resolved template, including point-effective values."""

        return stable_content_hash(content_fingerprint(self))


@dataclass(frozen=True, slots=True)
class GatePulseImplementationBinding:
    """Exact resolved pulse template for one gate invocation.

    ``pulse_template`` still carries implementation-local identities. The lowerer
    consuming this binding must instantiate it into a fresh hygienic scope.
    """

    call_id: CircuitOperationId
    key: GatePulseImplementationKey
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    pulse_template: PulseProgram


@dataclass(frozen=True, slots=True)
class GatePulseImplementationBindings:
    """Resolved implementation bindings for the gate calls in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[GatePulseImplementationBinding, ...]

    @property
    def gate_call_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(binding.call_id for binding in self.bindings)

    def binding_for(
        self, call_id: CircuitOperationId
    ) -> GatePulseImplementationBinding:
        for binding in self.bindings:
            if binding.call_id == call_id:
                return binding
        msg = f"gate call {call_id.value!r} has no pulse implementation binding"
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementationBindings:
    """Resolved implementation bindings for the measurements in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[MeasurementPulseImplementationBinding, ...]

    @property
    def measurement_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(binding.measurement_id for binding in self.bindings)

    def binding_for(
        self,
        measurement_id: CircuitOperationId,
    ) -> MeasurementPulseImplementationBinding:
        for binding in self.bindings:
            if binding.measurement_id == measurement_id:
                return binding
        msg = (
            f"measurement {measurement_id.value!r} has no pulse implementation binding"
        )
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class ResolvedPulseImplementations:
    """Point-effective gate and measurement implementations, unique by key."""

    gates: tuple[GatePulseImplementation, ...] = ()
    measurements: tuple[MeasurementPulseImplementation, ...] = ()

    def __post_init__(self) -> None:
        gates = tuple(self.gates)
        measurements = tuple(self.measurements)
        implementation_ids = tuple(entry.id for entry in (*gates, *measurements))
        if len(set(implementation_ids)) != len(implementation_ids):
            msg = "pulse implementation ids must be unique"
            raise ValueError(msg)
        gate_keys = tuple(entry.key for entry in gates)
        if len(set(gate_keys)) != len(gate_keys):
            msg = "gate pulse implementation keys must be unique"
            raise ValueError(msg)
        measurement_keys = tuple(entry.key for entry in measurements)
        if len(set(measurement_keys)) != len(measurement_keys):
            msg = "measurement pulse implementation keys must be unique"
            raise ValueError(msg)
        object.__setattr__(
            self, "gates", tuple(sorted(gates, key=lambda item: item.id.value))
        )
        object.__setattr__(
            self,
            "measurements",
            tuple(sorted(measurements, key=lambda item: item.id.value)),
        )


type PulseImplementationKey = (
    GatePulseImplementationKey | MeasurementPulseImplementationKey
)
type PulseImplementationBinding = (
    GatePulseImplementationBinding | MeasurementPulseImplementationBinding
)


def _binding_operation_id(binding: PulseImplementationBinding) -> CircuitOperationId:
    if isinstance(binding, GatePulseImplementationBinding):
        return binding.call_id
    return binding.measurement_id


class PulseImplementationBindingIssueCode(StrEnum):
    """Stable kinds of pulse implementation binding failure."""

    MISSING = "pulse_implementation_missing"


@dataclass(frozen=True, slots=True)
class PulseImplementationBindingIssue:
    """One operation without a resolved pulse implementation."""

    code: PulseImplementationBindingIssueCode
    operation_id: CircuitOperationId
    key: PulseImplementationKey
    message: str

    def __post_init__(self) -> None:
        if not self.message.strip():
            msg = "pulse implementation binding issue message must be non-empty"
            raise ValueError(msg)


class PulseImplementationBindingError(ValueError):
    """Aggregate exact implementation coverage failure."""

    def __init__(self, issues: tuple[PulseImplementationBindingIssue, ...]) -> None:
        if not issues:
            msg = "pulse implementation binding errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                issues,
                key=lambda issue: (
                    issue.operation_id.value,
                    issue.code.value,
                ),
            )
        )
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True)
class PulseImplementationBindings:
    """Resolved pulse implementations for every operation in one circuit."""

    circuit_id: CircuitId
    bindings: tuple[PulseImplementationBinding, ...]

    @property
    def operation_ids(self) -> tuple[CircuitOperationId, ...]:
        return tuple(_binding_operation_id(binding) for binding in self.bindings)

    @property
    def gates(self) -> GatePulseImplementationBindings:
        return GatePulseImplementationBindings(
            self.circuit_id,
            tuple(
                binding
                for binding in self.bindings
                if isinstance(binding, GatePulseImplementationBinding)
            ),
        )

    @property
    def measurements(self) -> MeasurementPulseImplementationBindings:
        return MeasurementPulseImplementationBindings(
            self.circuit_id,
            tuple(
                binding
                for binding in self.bindings
                if isinstance(binding, MeasurementPulseImplementationBinding)
            ),
        )

    def binding_for(
        self, operation_id: CircuitOperationId
    ) -> PulseImplementationBinding:
        for binding in self.bindings:
            if _binding_operation_id(binding) == operation_id:
                return binding
        msg = f"operation {operation_id.value!r} has no pulse implementation binding"
        raise KeyError(msg)


def bind_pulse_implementations(
    program: VerifiedCircuitProgram,
    implementations: ResolvedPulseImplementations,
) -> PulseImplementationBindings:
    """Bind every logical operation to its exact resolved pulse implementation."""

    gates_by_key = {entry.key: entry for entry in implementations.gates}
    measurements_by_key = {entry.key: entry for entry in implementations.measurements}

    bindings: list[PulseImplementationBinding] = []
    issues: list[PulseImplementationBindingIssue] = []
    for operation in program.operations:
        if isinstance(operation, GateCall):
            key: PulseImplementationKey = GatePulseImplementationKey.from_call(
                operation
            )
            selected: (
                GatePulseImplementation | MeasurementPulseImplementation | None
            ) = gates_by_key.get(key)
        else:
            assert isinstance(operation, Measure)  # noqa: S101
            key = MeasurementPulseImplementationKey.from_measurement(operation)
            selected = measurements_by_key.get(key)
        if selected is not None:
            if isinstance(operation, GateCall):
                assert isinstance(key, GatePulseImplementationKey)  # noqa: S101
                assert isinstance(selected, GatePulseImplementation)  # noqa: S101
                bindings.append(
                    GatePulseImplementationBinding(
                        call_id=operation.id,
                        key=key,
                        implementation_id=selected.id,
                        implementation_fingerprint=selected.fingerprint,
                        pulse_template=selected.pulse_template,
                    )
                )
            else:
                assert isinstance(key, MeasurementPulseImplementationKey)  # noqa: S101
                assert isinstance(selected, MeasurementPulseImplementation)  # noqa: S101
                bindings.append(
                    MeasurementPulseImplementationBinding(
                        measurement_id=operation.id,
                        key=key,
                        implementation_id=selected.id,
                        implementation_fingerprint=selected.fingerprint,
                        pulse_template=selected.pulse_template,
                    )
                )
            continue

        issues.append(
            PulseImplementationBindingIssue(
                code=PulseImplementationBindingIssueCode.MISSING,
                operation_id=operation.id,
                key=key,
                message=(
                    f"operation {operation.id.value!r} has no exact "
                    "pulse implementation"
                ),
            )
        )

    if issues:
        raise PulseImplementationBindingError(tuple(issues))

    circuit_id = program.program.id
    return PulseImplementationBindings(
        circuit_id,
        tuple(bindings),
    )


__all__ = [
    "GatePulseImplementation",
    "GatePulseImplementationArgument",
    "GatePulseImplementationBinding",
    "GatePulseImplementationBindings",
    "GatePulseImplementationKey",
    "MeasurementPulseImplementation",
    "MeasurementPulseImplementationBinding",
    "MeasurementPulseImplementationBindings",
    "MeasurementPulseImplementationKey",
    "PulseImplementationBinding",
    "PulseImplementationBindingError",
    "PulseImplementationBindingIssue",
    "PulseImplementationBindingIssueCode",
    "PulseImplementationBindings",
    "PulseImplementationKey",
    "ResolvedPulseImplementations",
    "bind_pulse_implementations",
]
