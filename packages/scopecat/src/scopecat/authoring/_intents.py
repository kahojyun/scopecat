"""Source-level authoring intents shared by assembly and resolution.

The objects in this module describe author intent only.  Turning them into
compiler and planning models is deliberately owned by :mod:`assembly` so the
data model does not depend on its lowering pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.authoring._value_refs import (
    ValueRef,
    internal_compute_value_ref,
    internal_input_value_ref,
)
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import ComputeFunction, ParameterKeyInput, RouteRef
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

type ClosedScalarValue = (
    Quantity | str | int | float | bool | None | EntityRef | PayloadValue
)
type StateRouteValue = ValueRef | ClosedScalarValue | tuple[ClosedScalarValue, ...]
type ComputeNodeInputValue = (
    ValueRef
    | RouteRef
    | Quantity
    | str
    | int
    | float
    | bool
    | None
    | EntityRef
    | PayloadValue
)
type PointSourceInput = ValueRef | None


@dataclass(frozen=True)
class StateEachIntent:
    relation: ValueRef
    resource: ValueRef | ClosedScalarValue
    field: str
    value: ValueRef | ClosedScalarValue
    route_entities: tuple[StateRouteValue, ...] = ()
    resource_port: str | None = None


ExperimentStateIntent = StateEachIntent


@dataclass(frozen=True)
class ComputeNodeIntent:
    id: str
    fn: ComputeFunction
    output_type: ValueType
    inputs: tuple[tuple[str, ComputeNodeInputValue], ...] = ()

    @property
    def result(self) -> ValueRef:
        return internal_compute_value_ref(self.id, self.output_type)


@dataclass(frozen=True)
class ModuleInputPort:
    id: str
    value_type: ValueType

    @property
    def ref(self) -> ValueRef:
        return internal_input_value_ref(self.id, self.value_type)


@dataclass(frozen=True)
class ParameterScanOverlayIntent:
    """One point-driven parameter-table cell overlay retained until linking."""

    table_id: str
    key: tuple[tuple[str, ParameterKeyInput], ...]
    column_id: str
    point_id: str


__all__ = [
    "ClosedScalarValue",
    "ComputeNodeInputValue",
    "ComputeNodeIntent",
    "ExperimentStateIntent",
    "ModuleInputPort",
    "ParameterScanOverlayIntent",
    "PointSourceInput",
    "StateEachIntent",
    "StateRouteValue",
]
