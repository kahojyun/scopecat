"""Source-level authoring intents shared by assembly and resolution.

The objects in this module describe author intent only.  Turning them into
compiler and planning models is deliberately owned by :mod:`assembly` so the
data model does not depend on its lowering pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat.authoring._value_refs import (
    ValueRef,
    internal_input_value_ref,
    internal_operation_result_value_ref,
)
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import (
    ComputeDeclarationKey,
    ParameterKeyInput,
    RouteRef,
)
from scopecat.compiler.relations.model import RowScopeId
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

if TYPE_CHECKING:
    from scopecat.authoring._module_ir import InvocationKey

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

type ActionFieldValue = ValueRef | ClosedScalarValue


@dataclass(frozen=True, slots=True)
class ModuleActionDecl:
    """One ordered, receipt-bearing instrument action invoked per point."""

    id: str
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[tuple[str, ActionFieldValue], ...] = ()
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.capability_id:
            msg = "action and capability ids must be non-empty"
            raise ValueError(msg)
        field_names = tuple(name for name, _value in self.fields)
        if any(not name for name in field_names):
            msg = "action field ids must be non-empty"
            raise ValueError(msg)
        if len(field_names) != len(set(field_names)):
            msg = f"action {self.id!r} field ids must be unique"
            raise ValueError(msg)

    @property
    def action_id(self) -> SymbolId:
        return SymbolId(scope=(*self.scope, "actions"), local_id=self.id)


@dataclass(frozen=True)
class StateEachIntent:
    relation: ValueRef
    row_scope_id: RowScopeId
    resource: ValueRef | ClosedScalarValue | None
    capability_id: str
    field_path: str
    value: ValueRef | ClosedScalarValue
    route_entities: tuple[StateRouteValue, ...] = ()
    resource_port: LogicalResourcePortId | None = None

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


ExperimentStateIntent = StateEachIntent


@dataclass(frozen=True, slots=True)
class ModuleOperationDecl:
    """Callable-free semantic declaration for one module-local operation."""

    id: str
    declaration_key: ComputeDeclarationKey
    output_type: ValueType
    inputs: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    scope: tuple[str, ...] = ()
    instance_path: tuple[InvocationKey, ...] = ()

    @property
    def operation_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)

    @property
    def result(self) -> ValueRef:
        return internal_operation_result_value_ref(
            self.operation_id,
            self.output_type,
            origin=(*self.instance_path, self.declaration_key),
        )


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
