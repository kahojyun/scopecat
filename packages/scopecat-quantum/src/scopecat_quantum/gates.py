"""Hardware-independent gate definitions and invocations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scopecat import Quantity

from scopecat_quantum._ids import CircuitOperationId, GateId, QubitId


def _runtime_object(value: object) -> object:
    """Erase a static field type before enforcing its runtime invariant."""

    return value


def _runtime_tuple(value: object) -> tuple[object, ...] | None:
    return cast("tuple[object, ...]", value) if isinstance(value, tuple) else None


class GateParameterKind(StrEnum):
    """Scalar parameter kinds understood by the foundational gate IR."""

    NUMBER = "number"
    INTEGER = "integer"
    ANGLE = "angle"


@dataclass(frozen=True, slots=True)
class GateParameterDefinition:
    """One named parameter in a gate definition."""

    id: str
    kind: GateParameterKind

    def __post_init__(self) -> None:
        raw_id = _runtime_object(self.id)
        raw_kind = _runtime_object(self.kind)
        if not isinstance(raw_id, str) or not raw_id.strip():
            msg = "gate parameter id must be a non-empty string"
            raise ValueError(msg)
        if not isinstance(raw_kind, GateParameterKind):
            msg = "gate parameter kind must be a GateParameterKind"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GateDefinition:
    """Reusable gate semantics, separate from any circuit invocation."""

    id: GateId
    qubit_arity: int
    parameters: tuple[GateParameterDefinition, ...] = ()

    def __post_init__(self) -> None:
        raw_id = _runtime_object(self.id)
        raw_arity = _runtime_object(self.qubit_arity)
        raw_parameters = _runtime_object(self.parameters)
        parameter_values = _runtime_tuple(raw_parameters)
        if not isinstance(raw_id, GateId):
            msg = "gate id must be a GateId"
            raise ValueError(msg)
        if (
            not isinstance(raw_arity, int)
            or isinstance(raw_arity, bool)
            or raw_arity <= 0
        ):
            msg = "gate qubit_arity must be a positive integer"
            raise ValueError(msg)
        if parameter_values is None or not all(
            isinstance(parameter, GateParameterDefinition)
            for parameter in parameter_values
        ):
            msg = "gate parameters must be a tuple of GateParameterDefinition values"
            raise ValueError(msg)


type GateArgumentValue = int | float | Quantity


def canonical_angle_value(value: Quantity) -> Quantity:
    """Return the stable radian representation used by exact match keys.

    The core quantity conversion owns the workspace-wide rounding rule, so
    ``180 deg`` and ``pi rad`` converge to the same transient value here.
    """

    return value.to("rad")


@dataclass(frozen=True, slots=True)
class GateArgument:
    """One explicitly named gate argument."""

    id: str
    value: GateArgumentValue

    def __post_init__(self) -> None:
        raw_id = _runtime_object(self.id)
        if not isinstance(raw_id, str) or not raw_id.strip():
            msg = "gate argument id must be a non-empty string"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GateCall:
    """One invocation of a gate definition on logical qubits."""

    id: CircuitOperationId
    gate_id: GateId
    qubits: tuple[QubitId, ...]
    arguments: tuple[GateArgument, ...] = ()


__all__ = [
    "GateArgument",
    "GateArgumentValue",
    "GateCall",
    "GateDefinition",
    "GateParameterDefinition",
    "GateParameterKind",
]
