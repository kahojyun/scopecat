"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from scopecat._frozen import freeze_json_mapping
from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    bind,
    resource_port,
)
from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_module_inputs,
    freeze_runtime_input,
)
from scopecat.authoring._handles import create_handle, replace_handle
from scopecat.authoring._intents import (
    ClosedScalarValue,
    ComputeNodeIntent,
    ExperimentStateIntent,
    ModuleInputPort,
    StateEachIntent,
    StateRouteValue,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    RecordAxis,
    RecordIntent,
    RecordSource,
    observable,
    record_axis_intents,
)
from scopecat.authoring._value_refs import (
    TableRow,
    ValueRef,
    internal_value_ref_input_id,
    internal_value_ref_source_kind,
)
from scopecat.authoring.value_types import (
    Entity as EntityType,
)
from scopecat.authoring.value_types import (
    Scalar as ScalarType,
)
from scopecat.authoring.value_types import (
    Series as SeriesType,
)
from scopecat.authoring.value_types import (
    Table as TableType,
)
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import (
    Compute,
    MetadataValue,
    ModuleInput,
    module_input_is_valid,
)
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue
from scopecat.results import MeasurementDType

if TYPE_CHECKING:
    from scopecat.authoring.templates import TemplateBuilder


type StateLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type BindingInput = StateLiteral | ValueRef
type StateRowValue = Callable[[TableRow], ValueRef]
type StateScalarInput = BindingInput | StateRowValue
type StateRouteInput = StateScalarInput | Sequence[StateLiteral]


def entity_input_ids_internal(
    input_ports: Sequence[ModuleInputPort],
) -> tuple[str, ...]:
    return tuple(
        port.id for port in input_ports if _is_entity_input_type(port.value_type)
    )


def _is_entity_input_type(value_type: ValueType) -> bool:
    if isinstance(value_type, ScalarType):
        return isinstance(value_type.atom, EntityType)
    if isinstance(value_type, SeriesType):
        return isinstance(value_type.item_type.atom, EntityType)
    return False


def _is_public_binding_input(value: object) -> bool:
    return value is None or isinstance(
        value,
        ValueRef | Quantity | EntityRef | PayloadValue | str | int | float | bool,
    )


def _resource_capabilities(requires: object) -> tuple[str, ...]:
    if isinstance(requires, str | bytes) or not isinstance(requires, Sequence):
        msg = "resource requires must be a sequence of capability ids"
        raise TypeError(msg)
    selected = cast("Sequence[object]", requires)
    if not all(isinstance(capability, str) and capability for capability in selected):
        msg = "resource requires must be a sequence of capability ids"
        raise TypeError(msg)
    return cast("tuple[str, ...]", tuple(selected))


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ModuleBuilder:
    """Fluent source builder for reusable experiment modules.

    Modules deliberately stop before point generation and record selection.
    That keeps a module composable: it can declare what it needs and what it can
    produce without also choosing how a notebook should scan it or which
    products a specific run should persist.
    """

    id: str | None = None
    invocations: tuple[ModuleInvocation, ...] = ()
    input_ports: tuple[ModuleInputPort, ...] = ()
    resources: tuple[ResourcePort, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __init__(self) -> None:
        msg = "ModuleBuilder is an opaque handle; create it with scopecat.module"
        raise TypeError(msg)

    @property
    def observables(self) -> tuple[str, ...]:
        return tuple(record.id for record in self.records)

    @property
    def has_fragments(self) -> bool:
        return any(
            (
                self.resources,
                self.invocations,
                self.input_ports,
                self.bindings,
                self.state_intents,
                self.compute_nodes,
                self.records,
                self.product_ports,
            )
        )

    def use(
        self,
        *modules: ExperimentModule | ModuleBuilder | ModuleInvocation,
    ) -> ModuleBuilder:
        from scopecat.authoring._module_construction import module_use_invocation

        invocations = tuple(module_use_invocation(module) for module in modules)
        return replace_handle(self, invocations=(*self.invocations, *invocations))

    def inputs(self, *values: ValueRef) -> ModuleBuilder:
        """Register typed input values declared with :func:`scopecat.input`."""

        existing = {port.id for port in self.input_ports}
        ports: list[ModuleInputPort] = []
        for value in values:
            input_id = internal_value_ref_input_id(value)
            if input_id is None:
                msg = "module inputs must be input value references"
                raise TypeError(msg)
            if input_id in existing:
                msg = f"module input {input_id!r} is already declared"
                raise ValueError(msg)
            existing.add(input_id)
            ports.append(ModuleInputPort(id=input_id, value_type=value.value_type))
        return replace_handle(self, input_ports=(*self.input_ports, *ports))

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: Sequence[str] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> ModuleBuilder:
        capabilities = _resource_capabilities(requires)
        for raw_value in cast("Sequence[object]", for_entities):
            if not isinstance(raw_value, ValueRef):
                msg = "resource for_entities must contain typed values"
                raise TypeError(msg)
            value = raw_value
            if not _is_entity_input_type(value.value_type):
                msg = "resource for_entities values must be entity-shaped"
                raise TypeError(msg)
            if internal_value_ref_source_kind(value) == "compute":
                msg = "resource for_entities cannot use compute outputs"
                raise TypeError(msg)
        selector = ResourceSelector(
            capabilities=capabilities,
            entity_inputs=tuple(for_entities),
        )
        return replace_handle(
            self,
            resources=(
                *self.resources,
                resource_port(id, selector),
            ),
        )

    def bind(
        self,
        port_path: str,
        value: BindingInput,
    ) -> ModuleBuilder:
        if not _is_public_binding_input(value):
            msg = "module bindings require a typed value or scalar literal"
            raise TypeError(msg)
        return replace_handle(
            self,
            bindings=(
                *self.bindings,
                bind(
                    port_path,
                    cast("BindingInput", _capture_state_literal(value)),
                ),
            ),
        )

    def state_each(
        self,
        relation: ValueRef,
        *,
        resource: StateScalarInput | None = None,
        resource_port: str | None = None,
        field: str,
        value: StateScalarInput,
        route_entities: Sequence[StateRouteInput] = (),
    ) -> ModuleBuilder:
        if not isinstance(relation.value_type, TableType):
            msg = "state_each requires a table-shaped typed value"
            raise TypeError(msg)
        if (resource is None) == (resource_port is None):
            msg = "state_each requires exactly one of resource or resource_port"
            raise TypeError(msg)
        row = TableRow._from_value(  # pyright: ignore[reportPrivateUsage]
            relation
        )
        selected_resource = resource_port if resource_port is not None else resource
        return replace_handle(
            self,
            state_intents=(
                *self.state_intents,
                StateEachIntent(
                    relation=relation,
                    resource=_state_scalar_expr(
                        _resolve_state_row_value(
                            selected_resource,
                            row,
                            path="state_each.resource",
                        )
                    ),
                    field=field,
                    value=_state_value_expr(
                        _resolve_state_row_value(
                            value,
                            row,
                            path="state_each.value",
                        )
                    ),
                    route_entities=tuple(
                        _state_route_expr(
                            _resolve_state_row_value(
                                entity,
                                row,
                                path="state_each.route_entities",
                            )
                        )
                        for entity in route_entities
                    ),
                    resource_port=resource_port,
                ),
            ),
        )

    def computes(self, *definitions: Compute) -> ModuleBuilder:
        """Register typed compute declarations and their output values."""

        existing = {node.id for node in self.compute_nodes}
        nodes: list[ComputeNodeIntent] = []
        for definition in definitions:
            if definition.id in existing:
                msg = f"module compute node {definition.id!r} is already declared"
                raise ValueError(msg)
            existing.add(definition.id)
            nodes.append(
                ComputeNodeIntent(
                    id=definition.id,
                    fn=definition.fn,
                    inputs=definition.inputs,
                    output_type=definition.output_type,
                )
            )
        return replace_handle(self, compute_nodes=(*self.compute_nodes, *nodes))

    def record(
        self,
        *record_ids: str,
        source: RecordSource = "instrument",
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[RecordAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        return replace_handle(
            self,
            records=(
                *self.records,
                *(
                    observable(
                        record_id,
                        source=source,
                        resource=resource,
                        capability=capability,
                        product_key=product_key,
                        unit=unit,
                        dtype=dtype,
                        axes=record_axis_intents(axes),
                        metadata=metadata,
                    )
                    for record_id in record_ids
                ),
            ),
        )

    def product(
        self,
        *product_ids: str,
        source: RecordSource = "instrument",
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[RecordAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        return replace_handle(
            self,
            product_ports=(
                *self.product_ports,
                *(
                    ModuleProductPort(
                        id=product_id,
                        kind="observable",
                        source=source,
                        resource=resource,
                        capability=capability,
                        product_key=product_key,
                        unit=unit,
                        dtype=dtype,
                        axes=record_axis_intents(axes),
                        metadata=freeze_json_mapping(metadata or {}),
                    )
                    for product_id in product_ids
                ),
            ),
        )

    def measure(self, *observable_ids: str) -> ModuleBuilder:
        return self.record(*observable_ids)

    def build(
        self,
        *,
        id: str | None = None,  # noqa: A002
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ExperimentModule:
        from scopecat.authoring._module_construction import (
            build_module_from_builder,
        )

        return build_module_from_builder(
            self,
            id=id,
            metadata=metadata,
        )

    def template(
        self,
        id: str,  # noqa: A002
        *,
        kind: str,
        experiment_id: str | None = None,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> TemplateBuilder:
        return self.build().template(
            id,
            kind=kind,
            experiment_id=experiment_id,
            label=label,
            description=description,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ModuleInvocation:
    module: ExperimentModule
    inputs: Mapping[str, ModuleInput] = field(default_factory=empty_frozen_mapping)

    def __init__(self) -> None:
        msg = (
            "ModuleInvocation is an opaque handle; create invocations by calling "
            "an ExperimentModule"
        )
        raise TypeError(msg)

    def __post_init__(self) -> None:
        invalid_values = sorted(
            input_id
            for input_id, value in self.inputs.items()
            if not module_input_is_valid(value)
        )
        if invalid_values:
            invalid = ", ".join(repr(input_id) for input_id in invalid_values)
            msg = (
                f"module {self.module.id!r} inputs require typed values or "
                f"closed literal data: {invalid}"
            )
            raise TypeError(msg)
        declared_inputs = set(module_exposed_input_types_internal(self.module))
        unknown_inputs = sorted(set(self.inputs) - declared_inputs)
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.module.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ExperimentModule:
    id: str
    invocations: tuple[ModuleInvocation, ...] = ()
    input_ports: tuple[ModuleInputPort, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __init__(self) -> None:
        msg = "ExperimentModule is an opaque handle; create it with module(...).build()"
        raise TypeError(msg)

    def __call__(self, **inputs: ModuleInput) -> ModuleInvocation:
        invalid_values = sorted(
            input_id
            for input_id, value in inputs.items()
            if not module_input_is_valid(value)
        )
        if invalid_values:
            invalid = ", ".join(repr(input_id) for input_id in invalid_values)
            msg = (
                f"module {self.id!r} inputs require typed values or "
                f"closed literal data: {invalid}"
            )
            raise TypeError(msg)
        return create_handle(
            ModuleInvocation,
            module=self,
            inputs=cast("Mapping[str, ModuleInput]", freeze_module_inputs(inputs)),
        )

    def template(
        self,
        id: str,  # noqa: A002
        *,
        kind: str,
        experiment_id: str | None = None,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> TemplateBuilder:
        from scopecat.authoring.templates import template_builder_from_module

        return template_builder_from_module(
            self,
            id,
            kind=kind,
            experiment_id=experiment_id,
            label=label,
            description=description,
            metadata=metadata,
        )


def module_exposed_input_types_internal(
    module: ExperimentModule,
) -> dict[str, ValueType]:
    """Collect typed inputs that remain unbound at a module boundary."""

    result: dict[str, ValueType] = {}
    for source in module.invocations:
        result.update(
            {
                input_id: value_type
                for input_id, value_type in module_exposed_input_types_internal(
                    source.module
                ).items()
                if input_id not in source.inputs
            }
        )
    result.update({port.id: port.value_type for port in module.input_ports})
    return result


def _state_scalar_expr(value: object) -> ValueRef | ClosedScalarValue:
    if isinstance(value, ValueRef):
        if not isinstance(value.value_type, ScalarType):
            msg = "state scalar value must be scalar-shaped"
            raise TypeError(msg)
        return value
    return cast("ClosedScalarValue", _capture_state_literal(value))


def _resolve_state_row_value(
    value: StateRouteInput | None,
    row: TableRow,
    *,
    path: str,
) -> StateRouteInput | None:
    if not callable(value):
        return value
    resolved = cast("object", value(row))
    if not isinstance(resolved, ValueRef):
        msg = f"{path} callback must return a typed value"
        raise TypeError(msg)
    return resolved


def _state_value_expr(value: object) -> ValueRef | ClosedScalarValue:
    if isinstance(value, ValueRef):
        return value
    return _state_scalar_expr(value)


def _state_route_expr(value: object) -> StateRouteValue:
    if isinstance(value, ValueRef):
        if isinstance(value.value_type, TableType):
            msg = "state route entity source must be scalar or series-shaped"
            raise TypeError(msg)
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        selected = cast("Sequence[object]", value)
        return cast(
            "tuple[ClosedScalarValue, ...]",
            tuple(_capture_state_literal(item) for item in selected),
        )
    return cast("ClosedScalarValue", _capture_state_literal(value))


def _capture_state_literal(value: object) -> object:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value.model_copy()
    return freeze_runtime_input(value)


__all__ = [
    "ExperimentModule",
    "ModuleBuilder",
    "ModuleInvocation",
]
