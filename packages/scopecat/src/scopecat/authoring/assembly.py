"""Module-based experiment assembly from structured authoring inputs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from scopecat._planning.parameter_patches import ParameterPatchSpec
from scopecat.authoring._bindings import (
    BindingIntent,
    EntitySource,
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    bind,
    build_route_intents,
    ports_by_id,
    require_port_capability,
    requires,
    resource_port,
)
from scopecat.authoring.context import ExperimentAuthoringContext
from scopecat.authoring.expressions import (
    BindingSpec,
    ExperimentVariable,
    Expression,
)
from scopecat.authoring.expressions import (
    param as param_expr,
)
from scopecat.authoring.expressions import (
    var as var_expr,
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
from scopecat.authoring.value_types import (
    ValueType,
    ValueValidationError,
    coerce_literal,
)
from scopecat.experiments import (
    ComputeNodeFunction,
    ComputeNodeInput,
    ComputeNodeSpec,
    ComputeResultRef,
    ExperimentSpec,
    RecordAxisSpec,
    RecordKind,
    RecordSource,
    RecordSpec,
    StateSpec,
    as_value_expr,
    bind_each,
    compute_result,
    set_state,
)
from scopecat.experiments import (
    record_axis as experiment_record_axis,
)
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue
from scopecat.parameters import ParameterDerivationSet, combine_parameter_derivations
from scopecat.relations import (
    CellValue,
    EvalContext,
    GridColumn,
    ParameterRelationData,
    RelationExpr,
    Row,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    grid,
    literal_rows,
    outer,
    param,
    range_values,
    values,
)
from scopecat.relations import (
    input_ref as relation_input_ref,
)
from scopecat.relations import input_series as relation_input_series
from scopecat.relations import input_table as relation_input_table
from scopecat.relations import (
    linspace as relation_linspace,
)
from scopecat.results import MeasurementDType

if TYPE_CHECKING:
    from scopecat.authoring.templates import TemplateBuilder

type VariableValue = ExperimentVariable | Expression
type VariableFactory = Callable[
    [ExperimentAuthoringContext, Mapping[str, object]], VariableValue
]
type ParameterDerivationInput = (
    ParameterDerivationSet | Sequence[ParameterDerivationSet] | None
)
type DataExpr = ScalarExpr | SeriesExpr | RelationExpr
type AxisSizeInput = (
    Expression | DataExpr | Quantity | float | Sequence[EntityRef | str]
)
type StateRouteExpr = ScalarExpr | SeriesExpr
type ComputeNodeInputValue = (
    Expression
    | DataExpr
    | Quantity
    | str
    | int
    | float
    | bool
    | EntityRef
    | Sequence[object]
    | ComputeResultRef
    | RouteBindingRef
)


@dataclass(frozen=True)
class DerivedVariableIntent:
    variable_id: str
    expression: Expression

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> ExperimentVariable:
        del ctx, inputs
        return ExperimentVariable(kind="derived", expression=self.expression)


@dataclass(frozen=True)
class ExplicitVariableIntent:
    variable_id: str
    value: VariableValue | VariableFactory

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> ExperimentVariable:
        value = self.value(ctx, inputs) if callable(self.value) else self.value
        if isinstance(value, ExperimentVariable):
            return value
        return ExperimentVariable(kind="derived", expression=value)


VariableIntent = DerivedVariableIntent | ExplicitVariableIntent
type PointSourceInput = RelationExpr | None


@dataclass(frozen=True)
class RecordAxisIntent:
    id: str
    size: AxisSizeInput
    kind: str | None = None
    unit: str | None = None
    entity_values: bool = False

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
        *,
        record_id: str,
    ) -> RecordAxisSpec:
        size, metadata = _static_axis_size(
            ctx,
            self.size,
            default=1,
            path=f"records.{record_id}.axes.{self.id}.size",
            inputs=inputs,
            entity_axis=self.entity_values,
        )
        return experiment_record_axis(
            self.id,
            size=size,
            kind=self.kind,
            unit=self.unit,
            metadata=metadata,
        )


@dataclass(frozen=True)
class RecordIntent:
    id: str
    kind: RecordKind = "observable"
    source: RecordSource = "instrument"
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxisIntent, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> RecordSpec:
        return RecordSpec(
            id=self.id,
            kind=self.kind,
            source=self.source,
            resource=self.resource,
            capability=self.capability,
            product_key=self.product_key,
            unit=self.unit,
            dtype=self.dtype,
            axes=[axis.build(ctx, inputs, record_id=self.id) for axis in self.axes],
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class ModuleProductPort:
    id: str
    kind: RecordKind = "observable"
    source: RecordSource = "instrument"
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxisIntent, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def build_record(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
        *,
        record_id: str,
    ) -> RecordSpec:
        return RecordIntent(
            id=record_id,
            kind=self.kind,
            source=self.source,
            resource=self.resource,
            capability=self.capability,
            product_key=self.product_key,
            unit=self.unit,
            dtype=self.dtype,
            axes=self.axes,
            metadata={"product_id": self.id, **self.metadata},
        ).build(ctx, inputs)


@dataclass(frozen=True)
class ProductSelectionIntent:
    product_id: str
    record_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateEachIntent:
    relation: RelationExpr
    resource: ScalarExpr
    field: str
    value: ScalarExpr | ComputeResultRef
    route_entities: tuple[StateRouteExpr, ...] = ()
    resource_port: str | None = None

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        resource_ports: Mapping[str, ResourcePort],
        inputs: Mapping[str, object],
    ) -> StateSpec:
        capability_id = _state_field_capability(ctx, self.field)
        if self.resource_port is not None:
            port = resource_ports.get(self.resource_port)
            if port is None:
                ctx.raise_diagnostic(
                    "module_unknown_resource_port",
                    "state binding references unknown resource port "
                    f"{self.resource_port}",
                    "state",
                )
            require_port_capability(ctx, port, capability_id)
        return bind_each(
            _bind_relation_input_refs(
                self.relation,
                inputs,
                unbound_to_outer=True,
            ),
            set_state(
                _bind_input_refs(
                    self.resource,
                    inputs,
                    unbound_to_outer=True,
                ),
                self.field,
                _bind_state_value(
                    self.value,
                    inputs,
                    unbound_to_outer=True,
                ),
                route_entities=tuple(
                    _bind_state_route_expr(
                        ctx,
                        entity,
                        inputs,
                        unbound_to_outer=True,
                    )
                    for entity in self.route_entities
                ),
            ),
        )


ExperimentStateIntent = StateEachIntent


@dataclass(frozen=True)
class RouteBindingRef:
    port_id: str


@dataclass(frozen=True)
class ComputeNodeIntent:
    id: str
    fn: ComputeNodeFunction
    inputs: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    route_ports: tuple[str, ...] = ()
    output_type: ScalarType | None = None

    def build(self, inputs: Mapping[str, object]) -> ComputeNodeSpec:
        return ComputeNodeSpec(
            id=self.id,
            inputs={
                name: _compute_node_input(value, inputs) for name, value in self.inputs
            },
            route_ports=list(self.route_ports),
            output_type=self.output_type,
            fn=self.fn,
        )


@dataclass(frozen=True)
class ModuleInputPort:
    id: str
    value_type: ValueType
    metadata: dict[str, Any] = field(default_factory=dict)


def _entity_input_ids(input_ports: Sequence[ModuleInputPort]) -> tuple[str, ...]:
    return tuple(
        port.id for port in input_ports if _is_entity_input_type(port.value_type)
    )


def _is_entity_input_type(value_type: ValueType) -> bool:
    if isinstance(value_type, ScalarType):
        return isinstance(value_type.atom, EntityType)
    if isinstance(value_type, SeriesType):
        return isinstance(value_type.item_type.atom, EntityType)
    return False


@dataclass(frozen=True)
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
    variables: tuple[VariableIntent, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

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
                self.variables,
                self.bindings,
                self.state_intents,
                self.compute_nodes,
                self.records,
                self.product_ports,
            )
        )

    def entity_inputs_from(self, *input_ids: str) -> ModuleBuilder:
        existing = {item.id for item in self.input_ports}
        return replace(
            self,
            input_ports=(
                *self.input_ports,
                *(
                    ModuleInputPort(
                        id=input_id,
                        value_type=ScalarType(EntityType()),
                        metadata={"role": "entity"},
                    )
                    for input_id in input_ids
                    if input_id not in existing
                ),
            ),
        )

    def use(
        self,
        *modules: ExperimentModule | ModuleBuilder | ModuleInvocation,
    ) -> ModuleBuilder:
        invocations = tuple(_module_use_invocation(module) for module in modules)
        return replace(self, invocations=(*self.invocations, *invocations))

    def entity(self, input_id: str) -> ModuleBuilder:
        return self.entity_inputs_from(input_id)

    def input(
        self,
        id: str,  # noqa: A002
        *,
        value_type: ValueType,
        metadata: Mapping[str, Any] | None = None,
    ) -> ModuleBuilder:
        return replace(
            self,
            input_ports=(
                *self.input_ports,
                ModuleInputPort(
                    id=id,
                    value_type=value_type,
                    metadata=dict(metadata or {}),
                ),
            ),
        )

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: ResourceSelector | Sequence[str] = (),
        for_entities: Sequence[EntitySource] = (),
    ) -> ModuleBuilder:
        selector = (
            requires
            if isinstance(requires, ResourceSelector)
            else ResourceSelector(
                capabilities=tuple(requires),
                entity_inputs=tuple(for_entities),
            )
        )
        return replace(
            self,
            resources=(
                *self.resources,
                resource_port(id, selector),
            ),
        )

    def derive(self, variable_id: str, expression: Expression) -> ModuleBuilder:
        return replace(
            self,
            variables=(*self.variables, derive(variable_id, expression)),
        )

    def variable(
        self,
        variable_id: str,
        value: VariableValue | VariableFactory,
    ) -> ModuleBuilder:
        return replace(
            self,
            variables=(*self.variables, variable(variable_id, value)),
        )

    def bind(
        self,
        port_path: str,
        value: Expression | ScalarExpr | ComputeResultRef | Quantity | float,
    ) -> ModuleBuilder:
        return replace(self, bindings=(*self.bindings, bind(port_path, value)))

    def state_each(
        self,
        relation: RelationExpr,
        *,
        resource: object | None = None,
        resource_port: str | None = None,
        field: str,
        value: object,
        route_entities: Sequence[object] = (),
    ) -> ModuleBuilder:
        if (resource is None) == (resource_port is None):
            msg = "state_each requires exactly one of resource or resource_port"
            raise TypeError(msg)
        selected_resource = resource_port if resource_port is not None else resource
        return replace(
            self,
            state_intents=(
                *self.state_intents,
                StateEachIntent(
                    relation=relation,
                    resource=_state_scalar_expr(selected_resource),
                    field=field,
                    value=_state_value_expr(value),
                    route_entities=tuple(
                        _state_route_expr(entity) for entity in route_entities
                    ),
                    resource_port=resource_port,
                ),
            ),
        )

    def compute(
        self,
        id: str,  # noqa: A002
        *,
        fn: ComputeNodeFunction,
        inputs: Mapping[str, ComputeNodeInputValue] | None = None,
        route_ports: Sequence[str] = (),
        output_type: ScalarType | None = None,
    ) -> ModuleBuilder:
        return replace(
            self,
            compute_nodes=(
                *self.compute_nodes,
                ComputeNodeIntent(
                    id=id,
                    fn=fn,
                    inputs=tuple((inputs or {}).items()),
                    route_ports=tuple(route_ports),
                    output_type=output_type,
                ),
            ),
        )

    def record(
        self,
        *record_ids: str,
        source: RecordSource = "instrument",
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[RecordAxisIntent] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> ModuleBuilder:
        return replace(
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
                        axes=axes,
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
        axes: Sequence[RecordAxisIntent] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> ModuleBuilder:
        return replace(
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
                        axes=tuple(axes),
                        metadata=dict(metadata or {}),
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
        metadata: Mapping[str, Any] | None = None,
    ) -> ExperimentModule:
        return _build_module_from_builder(
            self,
            metadata=metadata,
        )

    def template(
        self,
        id: str,  # noqa: A002
        *,
        kind: str,
        experiment_id: str | None = None,
        parameter_derivations: ParameterDerivationInput = None,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> TemplateBuilder:
        return self.build().template(
            id,
            kind=kind,
            experiment_id=experiment_id,
            parameter_derivations=parameter_derivations,
            label=label,
            description=description,
            metadata=metadata,
        )


@dataclass(frozen=True)
class ExperimentAssembly:
    """Internal source-level experiment IR produced before config linking."""

    experiment_id: str | None = None
    kind: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    input_ports: tuple[ModuleInputPort, ...] = ()
    entity_inputs: tuple[str, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    variables: tuple[VariableIntent, ...] = ()
    point_source: PointSourceInput = None
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    params: tuple[ParameterPatchSpec, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    record_selections: tuple[ProductSelectionIntent, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def combine(
        cls,
        *,
        experiment_id: str,
        kind: str,
        assemblies: Sequence[ExperimentAssembly],
        metadata: Mapping[str, Any] | None = None,
    ) -> ExperimentAssembly:
        if not assemblies:
            msg = "experiment assembly combine requires at least one assembly"
            raise ValueError(msg)
        merged_metadata: dict[str, Any] = {}
        merged_inputs: dict[str, object] = {}
        for assembly in assemblies:
            merged_inputs.update(assembly.inputs)
            merged_metadata.update(assembly.metadata)
        merged_metadata.update(dict(metadata or {}))
        resource_ports = _merge_resource_ports(
            tuple(item for assembly in assemblies for item in assembly.resource_ports)
        )
        return cls(
            experiment_id=experiment_id,
            kind=kind,
            inputs=merged_inputs,
            input_ports=tuple(
                item for assembly in assemblies for item in assembly.input_ports
            ),
            entity_inputs=tuple(
                item for assembly in assemblies for item in assembly.entity_inputs
            ),
            resource_ports=resource_ports,
            variables=tuple(
                item for assembly in assemblies for item in assembly.variables
            ),
            point_source=_combined_point_source(
                tuple(assembly.point_source for assembly in assemblies)
            ),
            bindings=tuple(
                item for assembly in assemblies for item in assembly.bindings
            ),
            state_intents=tuple(
                item for assembly in assemblies for item in assembly.state_intents
            ),
            params=tuple(item for assembly in assemblies for item in assembly.params),
            compute_nodes=tuple(
                item for assembly in assemblies for item in assembly.compute_nodes
            ),
            records=tuple(item for assembly in assemblies for item in assembly.records),
            product_ports=tuple(
                item for assembly in assemblies for item in assembly.product_ports
            ),
            record_selections=tuple(
                item for assembly in assemblies for item in assembly.record_selections
            ),
            parameter_derivations=_combined_parameter_derivations(
                id=f"{experiment_id}.parameter_derivations",
                derivations=tuple(
                    assembly.parameter_derivations for assembly in assemblies
                ),
            ),
            metadata=merged_metadata,
        )


@dataclass(frozen=True)
class ModuleInvocation:
    module: ExperimentModule
    inputs: dict[str, object] = field(default_factory=dict)

    def assemble(self) -> ExperimentAssembly:
        return self.module.assemble(**self.inputs)


@dataclass(frozen=True)
class ExperimentModule:
    id: str
    invocations: tuple[ModuleInvocation, ...] = ()
    input_ports: tuple[ModuleInputPort, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    variables: tuple[VariableIntent, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    parameter_derivations: ParameterDerivationSet | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __call__(self, **inputs: object) -> ModuleInvocation:
        return ModuleInvocation(module=self, inputs=dict(inputs))

    def template(
        self,
        id: str,  # noqa: A002
        *,
        kind: str,
        experiment_id: str | None = None,
        parameter_derivations: ParameterDerivationInput = None,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> TemplateBuilder:
        from scopecat.authoring.templates import template_builder_from_module

        return template_builder_from_module(
            self,
            id,
            kind=kind,
            experiment_id=experiment_id,
            parameter_derivations=_module_parameter_derivations(
                id,
                parameter_derivations,
            ),
            label=label,
            description=description,
            metadata=metadata,
        )

    def assemble(
        self,
        **inputs: object,
    ) -> ExperimentAssembly:
        own = ExperimentAssembly(
            inputs=dict(inputs),
            input_ports=self.input_ports,
            entity_inputs=_entity_input_ids(self.input_ports),
            resource_ports=_merge_resource_ports(self.resource_ports),
            variables=self.variables,
            bindings=self.bindings,
            state_intents=self.state_intents,
            compute_nodes=self.compute_nodes,
            records=self.records,
            product_ports=self.product_ports,
            parameter_derivations=self.parameter_derivations,
            metadata=dict(self.metadata),
        )
        if not self.invocations:
            return own
        source_assemblies = tuple(
            _localize_module_invocation_assembly(
                source,
                inputs,
                source_index=source_index,
            )
            for source_index, source in enumerate(self.invocations)
        )
        combined = ExperimentAssembly.combine(
            experiment_id=self.id,
            kind=self.id,
            assemblies=(*source_assemblies, own),
        )
        return replace(combined, experiment_id=None, kind=None)


def _module_from_parts(
    *,
    id: str,  # noqa: A002
    invocations: Sequence[ModuleInvocation] = (),
    input_ports: Sequence[ModuleInputPort] = (),
    resources: Sequence[ResourcePort] = (),
    variables: Sequence[VariableIntent] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    state_intents: Sequence[ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[RecordIntent] = (),
    product_ports: Sequence[ModuleProductPort] = (),
    parameter_derivations: ParameterDerivationInput = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExperimentModule:
    return _module(
        id=id,
        invocations=invocations,
        input_ports=input_ports,
        resources=resources,
        variables=variables,
        bindings=bindings,
        state_intents=state_intents,
        compute_nodes=compute_nodes,
        records=records,
        product_ports=product_ports,
        parameter_derivations=parameter_derivations,
        metadata=metadata,
    )


def _module(
    *,
    id: str,  # noqa: A002
    invocations: Sequence[ModuleInvocation] = (),
    input_ports: Sequence[ModuleInputPort] = (),
    resources: Sequence[ResourcePort] = (),
    variables: Sequence[VariableIntent] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    state_intents: Sequence[ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[RecordIntent] = (),
    product_ports: Sequence[ModuleProductPort] = (),
    parameter_derivations: ParameterDerivationInput = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExperimentModule:
    return ExperimentModule(
        id=id,
        invocations=tuple(invocations),
        input_ports=tuple(input_ports),
        resource_ports=tuple(resources),
        variables=tuple(variables),
        bindings=tuple(bindings),
        state_intents=tuple(state_intents),
        compute_nodes=tuple(compute_nodes),
        records=tuple(records),
        product_ports=tuple(product_ports),
        parameter_derivations=_module_parameter_derivations(id, parameter_derivations),
        metadata=dict(metadata or {}),
    )


def module(
    id: str | None = None,  # noqa: A002
    *,
    parameter_derivations: ParameterDerivationInput = None,
    metadata: Mapping[str, Any] | None = None,
) -> ModuleBuilder:
    derivation_set = (
        _module_parameter_derivations(id, parameter_derivations)
        if id is not None
        else _module_parameter_derivations("module", parameter_derivations)
    )
    return ModuleBuilder(
        id=id,
        invocations=(),
        input_ports=(),
        parameter_derivations=derivation_set,
        metadata=dict(metadata or {}),
    )


def _build_module_from_builder(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ExperimentModule:
    module_id = id or builder.id
    if not module_id:
        msg = "module builder requires an id before conversion to ExperimentModule"
        raise ValueError(msg)
    merged_metadata = dict(builder.metadata)
    merged_metadata.update(dict(metadata or {}))
    own_module = _module_from_parts(
        id=module_id,
        invocations=builder.invocations,
        input_ports=builder.input_ports,
        resources=builder.resources,
        variables=builder.variables,
        bindings=builder.bindings,
        state_intents=builder.state_intents,
        compute_nodes=builder.compute_nodes,
        records=builder.records,
        product_ports=builder.product_ports,
        parameter_derivations=builder.parameter_derivations,
        metadata=merged_metadata,
    )
    return own_module


def _module_use_invocation(
    module: ExperimentModule | ModuleBuilder | ModuleInvocation,
) -> ModuleInvocation:
    if isinstance(module, ModuleInvocation):
        return module
    if isinstance(module, ExperimentModule):
        return module()
    return module.build()()


def _module_invocation_inputs(
    invocation: ModuleInvocation,
    parent_inputs: Mapping[str, object],
    *,
    state_scope: bool = False,
) -> dict[str, object]:
    input_types = {port.id: port.value_type for port in invocation.module.input_ports}
    return {
        input_id: _module_invocation_input_expr(
            value,
            parent_inputs,
            input_id=input_id,
            value_type=input_types.get(input_id),
            state_scope=state_scope,
        )
        for input_id, value in invocation.inputs.items()
    }


def _localize_module_invocation_assembly(
    invocation: ModuleInvocation,
    parent_inputs: Mapping[str, object],
    *,
    source_index: int,
) -> ExperimentAssembly:
    local_inputs = _module_invocation_inputs(invocation, parent_inputs)
    state_inputs = _module_invocation_inputs(
        invocation,
        parent_inputs,
        state_scope=True,
    )
    assembly = invocation.module.assemble(**local_inputs)
    if not local_inputs:
        return assembly
    resource_ports, hidden_inputs = _localize_resource_port_input_refs(
        assembly.resource_ports,
        local_inputs,
        source_index=source_index,
    )
    return replace(
        assembly,
        inputs={
            **hidden_inputs,
            **{
                key: value
                for key, value in assembly.inputs.items()
                if key not in local_inputs
            },
        },
        input_ports=tuple(
            port for port in assembly.input_ports if port.id not in local_inputs
        ),
        entity_inputs=tuple(
            input_id
            for input_id in assembly.entity_inputs
            if input_id not in local_inputs
        ),
        resource_ports=resource_ports,
        bindings=tuple(
            _localize_binding_input_refs(binding, local_inputs)
            for binding in assembly.bindings
        ),
        state_intents=tuple(
            _localize_state_input_refs(intent, state_inputs)
            for intent in assembly.state_intents
        ),
        compute_nodes=tuple(
            _localize_compute_input_refs(node, local_inputs)
            for node in assembly.compute_nodes
        ),
        records=tuple(
            _localize_record_input_refs(record, local_inputs)
            for record in assembly.records
        ),
        product_ports=tuple(
            _localize_product_input_refs(product, local_inputs)
            for product in assembly.product_ports
        ),
    )


def _localize_resource_port_input_refs(
    ports: Sequence[ResourcePort],
    inputs: Mapping[str, object],
    *,
    source_index: int,
) -> tuple[tuple[ResourcePort, ...], dict[str, object]]:
    hidden_inputs: dict[str, object] = {}
    localized_ports: list[ResourcePort] = []
    for port in ports:
        entity_inputs: list[EntitySource] = []
        for source in port.selector.entity_inputs:
            localized: DataExpr | str
            if isinstance(source, str):
                value = inputs.get(source)
                if isinstance(value, ScalarExpr) and value.kind == "literal":
                    hidden_id = f"__local_entity_{source_index}_{source}"
                    hidden_inputs[hidden_id] = value.value
                    localized = hidden_id
                elif isinstance(value, ScalarExpr) and value.kind == "column":
                    localized = _required_name(value.name, "column.name")
                else:
                    localized = (
                        value
                        if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr)
                        else source
                    )
            else:
                localized = _substitute_value_input_refs(source, inputs)
            if isinstance(localized, RelationExpr):
                msg = (
                    "resource entity source must be scalar or series-shaped; "
                    "select table entity columns with table.entities(...)"
                )
                raise TypeError(msg)
            entity_inputs.append(localized)
        localized_ports.append(
            replace(
                port,
                selector=ResourceSelector(
                    capabilities=port.selector.capabilities,
                    entity_inputs=tuple(entity_inputs),
                ),
            )
        )
    return tuple(localized_ports), hidden_inputs


def _module_invocation_input_expr(
    value: object,
    parent_inputs: Mapping[str, object],
    *,
    input_id: str,
    value_type: ValueType | None,
    state_scope: bool = False,
) -> DataExpr:
    if isinstance(value, ScalarExpr):
        expression = _bind_input_refs(
            value,
            parent_inputs,
            unbound_to_outer=state_scope,
        )
        if state_scope:
            expression = _scalar_columns_to_outer(expression)
    elif isinstance(value, SeriesExpr | RelationExpr):
        expression = (
            _bind_value_input_refs(
                value,
                parent_inputs,
                unbound_to_outer=True,
            )
            if state_scope
            else _substitute_value_input_refs(value, parent_inputs)
        )
    elif isinstance(value, Expression):
        expression = _bind_input_refs(
            _expr_to_scalar(value),
            parent_inputs,
            unbound_to_outer=state_scope,
        )
        if state_scope:
            expression = _scalar_columns_to_outer(expression)
    elif value_type is None:
        return _literal_data_expr(value)
    else:
        coerced = coerce_literal(
            value_type,
            value,
            path=f"inputs.{input_id}",
        )
        if isinstance(value_type, ScalarType):
            expression = _literal(_input_cell(coerced))
        elif isinstance(value_type, SeriesType):
            expression = _series_input_value(input_id, coerced)
        else:
            expression = _table_input_value(input_id, coerced)
    _validate_data_expr_shape(
        expression,
        value_type,
        path=f"inputs.{input_id}",
    )
    return expression


def _validate_data_expr_shape(
    expression: DataExpr,
    value_type: ValueType | None,
    *,
    path: str,
) -> None:
    if value_type is None:
        return
    matches = (
        (isinstance(value_type, ScalarType) and isinstance(expression, ScalarExpr))
        or (isinstance(value_type, SeriesType) and isinstance(expression, SeriesExpr))
        or (isinstance(value_type, TableType) and isinstance(expression, RelationExpr))
    )
    if matches:
        return
    expected = (
        "scalar"
        if isinstance(value_type, ScalarType)
        else "series"
        if isinstance(value_type, SeriesType)
        else "table"
    )
    actual = (
        "scalar"
        if isinstance(expression, ScalarExpr)
        else "series"
        if isinstance(expression, SeriesExpr)
        else "table"
    )
    raise ValueValidationError(
        path,
        f"expected {expected}-shaped expression, got {actual}-shaped expression",
    )


def _localize_binding_input_refs(
    binding: ExperimentBindingIntent,
    inputs: Mapping[str, object],
) -> ExperimentBindingIntent:
    if isinstance(binding.value, ComputeResultRef):
        return binding
    expression = (
        binding.value
        if isinstance(binding.value, Expression | ScalarExpr)
        else Expression.from_value(binding.value)
    )
    return replace(
        binding,
        value=_substitute_input_refs(_expr_to_scalar(expression), inputs),
    )


def _localize_state_input_refs(
    intent: StateEachIntent,
    inputs: Mapping[str, object],
) -> StateEachIntent:
    return replace(
        intent,
        relation=_substitute_relation_input_refs(intent.relation, inputs),
        resource=_substitute_input_refs(intent.resource, inputs),
        value=(
            intent.value
            if isinstance(intent.value, ComputeResultRef)
            else _substitute_input_refs(intent.value, inputs)
        ),
        route_entities=tuple(
            _substitute_state_route_expr(entity, inputs)
            for entity in intent.route_entities
        ),
    )


def _scalar_columns_to_outer(expression: ScalarExpr) -> ScalarExpr:
    if expression.kind == "column":
        return outer(_required_name(expression.name, "column.name"))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _scalar_columns_to_outer(value)
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": _scalar_columns_to_outer(
                    _required_scalar(expression.left, "expression.left")
                ),
                "right": _scalar_columns_to_outer(
                    _required_scalar(expression.right, "expression.right")
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": _scalar_columns_to_outer(branch.condition),
                            "value": _scalar_columns_to_outer(branch.value),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _scalar_columns_to_outer(
                    _required_scalar(expression.fallback, "expression.fallback")
                ),
            }
        )
    return expression


def _localize_compute_input_refs(
    node: ComputeNodeIntent,
    inputs: Mapping[str, object],
) -> ComputeNodeIntent:
    return replace(
        node,
        inputs=tuple(
            (
                name,
                _localize_compute_input_value(value, inputs),
            )
            for name, value in node.inputs
        ),
    )


def _localize_compute_input_value(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
) -> ComputeNodeInputValue:
    if isinstance(value, ComputeResultRef | RouteBindingRef):
        return value
    if isinstance(value, Expression):
        return _substitute_input_refs(_expr_to_scalar(value), inputs)
    if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
        return _substitute_value_input_refs(value, inputs)
    return value


def _localize_record_input_refs(
    record: RecordIntent,
    inputs: Mapping[str, object],
) -> RecordIntent:
    return replace(
        record,
        axes=tuple(
            _localize_record_axis_input_refs(axis, inputs) for axis in record.axes
        ),
    )


def _localize_product_input_refs(
    product: ModuleProductPort,
    inputs: Mapping[str, object],
) -> ModuleProductPort:
    return replace(
        product,
        axes=tuple(
            _localize_record_axis_input_refs(axis, inputs) for axis in product.axes
        ),
    )


def _localize_record_axis_input_refs(
    axis: RecordAxisIntent,
    inputs: Mapping[str, object],
) -> RecordAxisIntent:
    if not isinstance(axis.size, Expression | ScalarExpr | SeriesExpr | RelationExpr):
        return axis
    expression = (
        _expr_to_scalar(axis.size) if isinstance(axis.size, Expression) else axis.size
    )
    return replace(
        axis,
        size=_substitute_value_input_refs(expression, inputs),
    )


_EMPTY_INPUT_RESOLUTION: frozenset[str] = frozenset()


def _descend_input_resolution(
    input_name: str,
    resolving: frozenset[str],
) -> frozenset[str]:
    if input_name in resolving:
        msg = f"cyclic module input reference: {input_name}"
        raise ValueError(msg)
    return resolving | {input_name}


def _substitute_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> ScalarExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        value = inputs.get(input_name)
        if isinstance(value, ScalarExpr):
            if value.kind == "input" and value.name == input_name:
                return value
            return _substitute_input_refs(
                value,
                inputs,
                resolving=_descend_input_resolution(input_name, resolving),
            )
        return expression
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _substitute_input_refs(
                        value,
                        inputs,
                        resolving=resolving,
                    )
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": _substitute_input_refs(
                    _required_scalar(expression.left, "expression.left"),
                    inputs,
                    resolving=resolving,
                ),
                "right": _substitute_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
                    resolving=resolving,
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": _substitute_input_refs(
                                branch.condition,
                                inputs,
                                resolving=resolving,
                            ),
                            "value": _substitute_input_refs(
                                branch.value,
                                inputs,
                                resolving=resolving,
                            ),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _substitute_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                    resolving=resolving,
                ),
            }
        )
    return expression


def _substitute_value_input_refs(
    expression: DataExpr,
    inputs: Mapping[str, object],
    *,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> DataExpr:
    if isinstance(expression, ScalarExpr):
        return _substitute_input_refs(expression, inputs, resolving=resolving)
    if isinstance(expression, SeriesExpr):
        return _substitute_series_input_refs(
            expression,
            inputs,
            resolving=resolving,
        )
    return _substitute_relation_input_refs(
        expression,
        inputs,
        resolving=resolving,
    )


def _substitute_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> SeriesExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        value = inputs.get(input_name)
        if isinstance(value, SeriesExpr):
            if value.kind == "input" and value.name == input_name:
                return value
            return _substitute_series_input_refs(
                value,
                inputs,
                resolving=_descend_input_resolution(input_name, resolving),
            )
        if isinstance(value, ScalarExpr | RelationExpr):
            msg = f"series input {input_name!r} must bind to a series expression"
            raise TypeError(msg)
        return expression
    update: dict[str, object] = {}
    for field_name in ("start", "stop", "step"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = _substitute_input_refs(
                value,
                inputs,
                resolving=resolving,
            )
    if expression.source is not None:
        update["source"] = _substitute_relation_input_refs(
            expression.source,
            inputs,
            resolving=resolving,
        )
    return expression.model_copy(update=update) if update else expression


def _substitute_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> RelationExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        value = inputs.get(input_name)
        if isinstance(value, RelationExpr):
            if value.kind == "input" and value.name == input_name:
                return value
            return _substitute_relation_input_refs(
                value,
                inputs,
                resolving=_descend_input_resolution(input_name, resolving),
            )
        if isinstance(value, ScalarExpr | SeriesExpr):
            msg = f"table input {input_name!r} must bind to a table expression"
            raise TypeError(msg)
        return expression
    update: dict[str, object] = {}
    for field_name in ("source", "left", "right"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = _substitute_relation_input_refs(
                value,
                inputs,
                resolving=resolving,
            )
    if expression.columns is not None:
        update["columns"] = {
            name: _substitute_grid_column_input_refs(
                column,
                inputs,
                resolving=resolving,
            )
            for name, column in expression.columns.items()
        }
    if expression.condition is not None:
        update["condition"] = _substitute_input_refs(
            expression.condition,
            inputs,
            resolving=resolving,
        )
    if expression.new_columns is not None:
        update["new_columns"] = {
            name: _substitute_input_refs(
                value,
                inputs,
                resolving=resolving,
            )
            for name, value in expression.new_columns.items()
        }
    return expression.model_copy(update=update) if update else expression


def _substitute_grid_column_input_refs(
    column: GridColumn,
    inputs: Mapping[str, object],
    *,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> GridColumn:
    if column.scalar is not None:
        return column.model_copy(
            update={
                "scalar": _substitute_input_refs(
                    column.scalar,
                    inputs,
                    resolving=resolving,
                )
            }
        )
    if column.series is not None:
        return column.model_copy(
            update={
                "series": _substitute_series_input_refs(
                    column.series,
                    inputs,
                    resolving=resolving,
                )
            }
        )
    if column.relation is not None:
        return column.model_copy(
            update={
                "relation": _substitute_relation_input_refs(
                    column.relation,
                    inputs,
                    resolving=resolving,
                )
            }
        )
    return column


def _bind_value_input_refs(
    expression: DataExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> DataExpr:
    if isinstance(expression, ScalarExpr):
        return _bind_input_refs(
            expression,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=resolving,
        )
    if isinstance(expression, SeriesExpr):
        return _bind_series_input_refs(
            expression,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=resolving,
        )
    return _bind_relation_input_refs(
        expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
        resolving=resolving,
    )


def _bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> SeriesExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        selected = _series_input_value(input_name, inputs[input_name])
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return _bind_series_input_refs(
            selected,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=_descend_input_resolution(input_name, resolving),
        )
    update: dict[str, object] = {}
    for field_name in ("start", "stop", "step"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = _bind_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=resolving,
            )
    if expression.source is not None:
        update["source"] = _bind_relation_input_refs(
            expression.source,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=resolving,
        )
    return expression.model_copy(update=update) if update else expression


def _bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> RelationExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        selected = _table_input_value(input_name, inputs[input_name])
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return _bind_relation_input_refs(
            selected,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=_descend_input_resolution(input_name, resolving),
        )
    update: dict[str, object] = {}
    for field_name in ("source", "left", "right"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = _bind_relation_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=resolving,
            )
    if expression.columns is not None:
        update["columns"] = {
            name: _bind_grid_column_input_refs(
                column,
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=resolving,
            )
            for name, column in expression.columns.items()
        }
    if expression.condition is not None:
        update["condition"] = _bind_input_refs(
            expression.condition,
            inputs,
            unbound_to_outer=unbound_to_outer,
            resolving=resolving,
        )
    if expression.new_columns is not None:
        update["new_columns"] = {
            name: _bind_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=resolving,
            )
            for name, value in expression.new_columns.items()
        }
    return expression.model_copy(update=update) if update else expression


def _bind_grid_column_input_refs(
    column: GridColumn,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> GridColumn:
    if column.scalar is not None:
        return column.model_copy(
            update={
                "scalar": _bind_input_refs(
                    column.scalar,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                )
            }
        )
    if column.series is not None:
        return column.model_copy(
            update={
                "series": _bind_series_input_refs(
                    column.series,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                )
            }
        )
    if column.relation is not None:
        return column.model_copy(
            update={
                "relation": _bind_relation_input_refs(
                    column.relation,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                )
            }
        )
    return column


def _series_input_value(input_name: str, value: object) -> SeriesExpr:
    if isinstance(value, SeriesExpr):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = cast("Sequence[object]", value)
        return values([_input_cell(item) for item in sequence])
    msg = f"series input {input_name!r} must bind to a sequence"
    raise TypeError(msg)


def _table_input_value(input_name: str, value: object) -> RelationExpr:
    if isinstance(value, RelationExpr):
        return value
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {input_name!r} must bind to a sequence of rows"
        raise TypeError(msg)
    rows: list[dict[str, CellValue]] = []
    sequence = cast("Sequence[object]", value)
    for index, item in enumerate(sequence):
        if not isinstance(item, Mapping):
            msg = f"table input {input_name!r} row {index} must be a mapping"
            raise TypeError(msg)
        row = cast("Mapping[object, object]", item)
        rows.append({str(name): _input_cell(cell) for name, cell in row.items()})
    return literal_rows(rows)


def _literal_data_expr(value: object) -> DataExpr:
    if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
        return value
    if isinstance(value, Expression):
        return _expr_to_scalar(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = cast("Sequence[object]", value)
        if sequence and all(isinstance(item, Mapping) for item in sequence):
            return _table_input_value("literal", sequence)
        return values([_input_cell(item) for item in sequence])
    return _literal(_input_cell(value))


def derive(variable_id: str, expression: Expression) -> DerivedVariableIntent:
    return DerivedVariableIntent(variable_id=variable_id, expression=expression)


def variable(
    variable_id: str,
    value: VariableValue | VariableFactory,
) -> ExplicitVariableIntent:
    return ExplicitVariableIntent(variable_id=variable_id, value=value)


def var_ref(variable_id: str) -> Expression:
    return var_expr(variable_id)


def param_ref(parameter_id: str) -> Expression:
    return param_expr(parameter_id)


def input_ref(input_id: str) -> ScalarExpr:
    return relation_input_ref(input_id)


def input_series(input_id: str) -> SeriesExpr:
    return relation_input_series(input_id)


def input_table(input_id: str) -> RelationExpr:
    return relation_input_table(input_id)


def route(port_id: str) -> RouteBindingRef:
    return RouteBindingRef(port_id=port_id)


def record_axis(
    id: str,  # noqa: A002
    *,
    size: AxisSizeInput,
    kind: str | None = None,
    unit: str | None = None,
) -> RecordAxisIntent:
    return RecordAxisIntent(id=id, size=size, kind=kind, unit=unit)


def entity_axis(
    id: str,  # noqa: A002
    entities: Expression | ScalarExpr | SeriesExpr | Sequence[EntityRef | str],
) -> RecordAxisIntent:
    return replace(
        record_axis(
            id,
            size=entities,
            kind="entity",
            unit=None,
        ),
        entity_values=True,
    )


def shot_axis(size: Expression | ScalarExpr | Quantity | float) -> RecordAxisIntent:
    return record_axis("shot", size=size, kind="shot", unit="count")


def observable(
    id: str,  # noqa: A002
    *,
    source: RecordSource = "instrument",
    unit: str | None = "ratio",
    resource: str | None = None,
    capability: str | None = None,
    product_key: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[RecordAxisIntent] = (),
    metadata: Mapping[str, Any] | None = None,
) -> RecordIntent:
    return RecordIntent(
        id=id,
        kind="observable",
        source=source,
        resource=resource,
        capability=capability,
        product_key=product_key,
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=dict(metadata or {}),
    )


def record_product(
    product_id: str,
    *,
    record_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ProductSelectionIntent:
    return ProductSelectionIntent(
        product_id=product_id,
        record_id=record_id,
        metadata=dict(metadata or {}),
    )


def _validate_entity_inputs(
    ctx: ExperimentAuthoringContext,
    entity_inputs: tuple[str, ...],
    inputs: Mapping[str, object],
) -> None:
    for input_id in entity_inputs:
        if input_id not in inputs:
            continue
        value = inputs.get(input_id)
        if isinstance(value, str) and value:
            ctx.require_entity(value)
            continue
        if isinstance(value, EntityRef):
            ctx.require_entity(value)
            continue
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            selected = cast("Sequence[EntityRef | str]", value)
            ctx.require_entities(selected)
            continue
        if not value:
            ctx.raise_diagnostic(
                "module_entity_input_invalid",
                f"module entity input {input_id} must be an entity or entity series",
                input_id,
            )
        ctx.raise_diagnostic(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity or entity series",
            input_id,
        )


def _lower_records(
    ctx: ExperimentAuthoringContext,
    record_intents: Sequence[RecordIntent],
    inputs: Mapping[str, object],
) -> list[RecordSpec]:
    return [record_intent.build(ctx, inputs) for record_intent in record_intents]


def _lower_product_selections(
    ctx: ExperimentAuthoringContext,
    selections: Sequence[ProductSelectionIntent],
    product_ports: Sequence[ModuleProductPort],
    inputs: Mapping[str, object],
) -> list[RecordSpec]:
    product_by_id = _product_ports_by_id(ctx, product_ports)
    records: list[RecordSpec] = []
    for selection in selections:
        product = product_by_id.get(selection.product_id)
        if product is None:
            ctx.raise_diagnostic(
                "module_product_unknown",
                f"experiment selects unknown product {selection.product_id}",
                "records",
            )
        record = product.build_record(
            ctx,
            inputs,
            record_id=selection.record_id or selection.product_id,
        )
        records.append(
            record.model_copy(
                update={"metadata": {**record.metadata, **selection.metadata}}
            )
        )
    return records


def link_experiment_assembly(
    assembly: ExperimentAssembly,
    ctx: ExperimentAuthoringContext,
) -> ExperimentSpec:
    if not assembly.experiment_id:
        ctx.raise_diagnostic(
            "experiment_assembly_entrypoint_missing_id",
            "experiment assembly must be linked with an experiment id",
            "experiment_id",
        )
    if not assembly.kind:
        ctx.raise_diagnostic(
            "experiment_assembly_entrypoint_missing_kind",
            "experiment assembly must be linked with an experiment kind",
            "kind",
        )
    _validate_assembly_conflicts(ctx, assembly)
    inputs = _coerce_assembly_inputs(ctx, assembly.input_ports, assembly.inputs)
    _validate_entity_inputs(ctx, assembly.entity_inputs, inputs)
    resource_ports = ports_by_id(ctx, assembly.resource_ports)
    route_intents = build_route_intents(
        ctx,
        assembly.resource_ports,
        inputs=inputs,
    )
    variables = {
        intent.variable_id: intent.build(ctx, inputs) for intent in assembly.variables
    }
    bindings = [binding.build(ctx, resource_ports) for binding in assembly.bindings]
    points = _points_relation(
        ctx,
        _build_point_source(assembly.point_source, inputs),
        variables,
        inputs=inputs,
        input_ports=assembly.input_ports,
        entity_input_ids=assembly.entity_inputs,
    )
    records = [
        *_lower_records(ctx, assembly.records, inputs),
        *_lower_product_selections(
            ctx,
            assembly.record_selections,
            assembly.product_ports,
            inputs,
        ),
    ]
    return ExperimentSpec(
        id=assembly.experiment_id,
        kind=assembly.kind,
        points=points,
        route_intents=route_intents,
        compute_nodes=[node.build(inputs) for node in assembly.compute_nodes],
        params=list(assembly.params),
        state=[
            *_state_specs(bindings, inputs=inputs),
            *(
                intent.build(ctx, resource_ports, inputs)
                for intent in assembly.state_intents
            ),
        ],
        records=records,
        metadata=dict(assembly.metadata),
    )


def _validate_assembly_conflicts(
    ctx: ExperimentAuthoringContext,
    assembly: ExperimentAssembly,
) -> None:
    _reject_duplicates(
        ctx,
        ids=[variable.variable_id for variable in assembly.variables],
        code="module_variable_duplicate",
        message="experiment assembly defines duplicate variables",
        path="variables",
    )
    _reject_duplicates(
        ctx,
        ids=[
            *(record.id for record in assembly.records),
            *(
                selection.record_id or selection.product_id
                for selection in assembly.record_selections
            ),
        ],
        code="module_record_duplicate",
        message="experiment assembly defines duplicate records",
        path="records",
    )
    _reject_duplicates(
        ctx,
        ids=[product.id for product in assembly.product_ports],
        code="module_product_duplicate",
        message="experiment assembly defines duplicate products",
        path="products",
    )
    _reject_duplicates(
        ctx,
        ids=[node.id for node in assembly.compute_nodes],
        code="module_compute_node_duplicate",
        message="experiment assembly defines duplicate program nodes",
        path="compute_nodes",
    )


def _coerce_assembly_inputs(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ModuleInputPort],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    declared: dict[str, ValueType] = {}
    for port in ports:
        existing = declared.get(port.id)
        if existing is not None and existing != port.value_type:
            ctx.raise_diagnostic(
                "module_input_type_conflict",
                f"module input {port.id} has incompatible value types",
                f"inputs.{port.id}",
            )
        declared[port.id] = port.value_type
    result = dict(inputs)
    for input_id, value_type in declared.items():
        if input_id not in result:
            continue
        value = result[input_id]
        if isinstance(value, Expression):
            expression = _expr_to_scalar(value)
            try:
                _validate_data_expr_shape(
                    expression,
                    value_type,
                    path=f"inputs.{input_id}",
                )
            except ValueValidationError as error:
                ctx.raise_diagnostic(
                    "module_input_type_mismatch",
                    str(error),
                    error.path,
                )
            continue
        if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
            try:
                _validate_data_expr_shape(
                    value,
                    value_type,
                    path=f"inputs.{input_id}",
                )
            except ValueValidationError as error:
                ctx.raise_diagnostic(
                    "module_input_type_mismatch",
                    str(error),
                    error.path,
                )
            continue
        try:
            result[input_id] = coerce_literal(
                value_type,
                value,
                path=f"inputs.{input_id}",
            )
        except ValueValidationError as error:
            ctx.raise_diagnostic(
                "module_input_type_mismatch",
                str(error),
                error.path,
            )
    return result


def _product_ports_by_id(
    ctx: ExperimentAuthoringContext,
    product_ports: Sequence[ModuleProductPort],
) -> dict[str, ModuleProductPort]:
    _reject_duplicates(
        ctx,
        ids=[product.id for product in product_ports],
        code="module_product_duplicate",
        message="experiment assembly defines duplicate products",
        path="products",
    )
    return {product.id: product for product in product_ports}


def _merge_resource_ports(roles: Sequence[ResourcePort]) -> tuple[ResourcePort, ...]:
    merged: dict[str, ResourcePort] = {}
    for role in roles:
        existing = merged.get(role.id)
        if existing is None:
            merged[role.id] = role
            continue
        capabilities = tuple(
            dict.fromkeys(
                (*existing.selector.capabilities, *role.selector.capabilities)
            )
        )
        entity_inputs = tuple(
            _unique_values(
                (*existing.selector.entity_inputs, *role.selector.entity_inputs)
            )
        )
        merged[role.id] = ResourcePort(
            id=role.id,
            selector=ResourceSelector(
                capabilities=capabilities,
                entity_inputs=entity_inputs,
            ),
        )
    return tuple(merged.values())


def _unique_values[T](values: Sequence[T]) -> list[T]:
    selected: list[T] = []
    for value in values:
        if value not in selected:
            selected.append(value)
    return selected


def _reject_duplicates(
    ctx: ExperimentAuthoringContext,
    *,
    ids: Sequence[str],
    code: str,
    message: str,
    path: str,
) -> None:
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        ctx.raise_diagnostic(
            code,
            f"{message}: {', '.join(duplicates)}",
            path,
        )


def _points_relation(
    ctx: ExperimentAuthoringContext,
    point_source: RelationExpr | None,
    variables: Mapping[str, ExperimentVariable],
    *,
    inputs: Mapping[str, object],
    input_ports: Sequence[ModuleInputPort] = (),
    entity_input_ids: Sequence[str] = (),
) -> RelationExpr:
    columns: dict[str, object] = {}
    derived: dict[str, ScalarExpr] = {}
    for variable_id, variable in variables.items():
        if variable.kind == "linspace":
            start = _required_quantity(variable.start, variable_id)
            stop = _required_quantity(variable.stop, variable_id)
            columns[variable_id] = relation_linspace(
                start.value,
                stop.value,
                _required_int(variable.count, variable_id),
                unit=start.unit,
            )
        elif variable.kind == "points":
            columns[variable_id] = values(
                _required_quantities(variable.points, variable_id)
            )
        elif variable.kind == "range":
            start = _required_quantity(variable.start, variable_id)
            stop = _required_quantity(variable.stop, variable_id)
            step = _required_quantity(variable.step, variable_id)
            columns[variable_id] = range_values(
                start.value,
                stop.value,
                step.value,
                unit=start.unit,
                include_stop=True,
            )
        elif variable.kind == "derived":
            derived[variable_id] = _expr_to_scalar(
                _required_expression(variable.expression, variable_id)
            )
    relation = grid(**columns) if columns else literal_rows([{}])
    if point_source is not None:
        relation = point_source.cross(relation) if columns else point_source
    if derived:
        relation = relation.with_columns(**derived)
    rows = _coerce_point_input_values(
        ctx,
        relation.evaluate(
            ctx.parameter_view,
            inputs=_input_row(inputs),
        ),
        input_ports=input_ports,
    )
    return literal_rows(
        _resolve_point_entities(
            ctx,
            rows,
            entity_input_ids=entity_input_ids,
        )
    )


def _coerce_point_input_values(
    ctx: ExperimentAuthoringContext,
    rows: Sequence[Row],
    *,
    input_ports: Sequence[ModuleInputPort],
) -> list[Row]:
    scalar_types = {
        port.id: port.value_type
        for port in input_ports
        if isinstance(port.value_type, ScalarType)
    }
    result: list[Row] = []
    for row_index, row in enumerate(rows):
        selected = dict(row)
        for column, value_type in scalar_types.items():
            if column not in selected:
                continue
            try:
                selected[column] = cast(
                    "CellValue",
                    coerce_literal(
                        value_type,
                        selected[column],
                        path=f"points.{row_index}.{column}",
                    ),
                )
            except ValueValidationError as error:
                ctx.raise_diagnostic(
                    "module_point_value_type_mismatch",
                    str(error),
                    error.path,
                )
        result.append(selected)
    return result


def _resolve_point_entities(
    ctx: ExperimentAuthoringContext,
    rows: Sequence[Row],
    *,
    entity_input_ids: Sequence[str] = (),
) -> list[Row]:
    entity_columns = set(entity_input_ids)
    return [
        {
            name: _resolve_point_entity_value(
                ctx,
                value,
                resolve_strings=name in entity_columns,
            )
            for name, value in row.items()
        }
        for row in rows
    ]


def _resolve_point_entity_value(
    ctx: ExperimentAuthoringContext,
    value: CellValue,
    *,
    resolve_strings: bool = False,
) -> CellValue:
    if isinstance(value, EntityRef):
        return ctx.require_entity(value)
    if resolve_strings and isinstance(value, str) and value:
        return ctx.require_entity(value)
    return value


def _combined_point_source(
    point_sources: Sequence[PointSourceInput],
) -> PointSourceInput:
    selected = [
        point_source for point_source in point_sources if point_source is not None
    ]
    if not selected:
        return None
    return _combined_point_source_input(selected)


def _combined_point_source_input(
    point_sources: Sequence[RelationExpr],
) -> PointSourceInput:
    if not point_sources:
        return None
    if len(point_sources) == 1:
        return point_sources[0]
    return _combine_relations(point_sources)


def _combine_relations(relations: Sequence[RelationExpr]) -> RelationExpr:
    if not relations:
        return literal_rows([{}])
    relation = relations[0]
    for next_relation in relations[1:]:
        relation = relation.cross(next_relation)
    return relation


def _build_point_source(
    point_source: PointSourceInput,
    inputs: Mapping[str, object],
) -> RelationExpr | None:
    del inputs
    return point_source


def _bind_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> ScalarExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return outer(input_name) if unbound_to_outer else col(input_name)
        value = inputs[input_name]
        next_resolving = _descend_input_resolution(input_name, resolving)
        if isinstance(value, ScalarExpr):
            if value.kind == "input" and value.name == input_name:
                return outer(input_name) if unbound_to_outer else col(input_name)
            bound = _bind_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=next_resolving,
            )
            return _scalar_columns_to_outer(bound) if unbound_to_outer else bound
        if isinstance(value, Expression):
            bound = _bind_input_refs(
                _expr_to_scalar(value),
                inputs,
                unbound_to_outer=unbound_to_outer,
                resolving=next_resolving,
            )
            return _scalar_columns_to_outer(bound) if unbound_to_outer else bound
        return _literal(_input_cell(value))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _bind_input_refs(
                        value,
                        inputs,
                        unbound_to_outer=unbound_to_outer,
                        resolving=resolving,
                    )
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": _bind_input_refs(
                    _required_scalar(expression.left, "expression.left"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                ),
                "right": _bind_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": _bind_input_refs(
                                branch.condition,
                                inputs,
                                unbound_to_outer=unbound_to_outer,
                                resolving=resolving,
                            ),
                            "value": _bind_input_refs(
                                branch.value,
                                inputs,
                                unbound_to_outer=unbound_to_outer,
                                resolving=resolving,
                            ),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _bind_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    resolving=resolving,
                ),
            }
        )
    return expression


def bind_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    return _bind_input_refs(expression, inputs)


def bind_value_input_refs(
    expression: DataExpr,
    inputs: Mapping[str, object],
) -> DataExpr:
    return _bind_value_input_refs(expression, inputs)


def _value_input_refs(expression: DataExpr) -> tuple[str, ...]:
    refs: set[str] = set()
    _collect_value_input_refs(expression, refs)
    return tuple(sorted(refs))


def _collect_value_input_refs(expression: DataExpr, refs: set[str]) -> None:
    if isinstance(expression, ScalarExpr):
        _collect_scalar_input_refs(expression, refs)
        return
    if isinstance(expression, SeriesExpr):
        if expression.kind == "input" and expression.name:
            refs.add(expression.name)
        for bound in (expression.start, expression.stop, expression.step):
            if bound is not None:
                _collect_scalar_input_refs(bound, refs)
        if expression.source is not None:
            _collect_relation_input_refs(expression.source, refs)
        return
    _collect_relation_input_refs(expression, refs)


def _collect_scalar_input_refs(expression: ScalarExpr, refs: set[str]) -> None:
    if expression.kind == "input" and expression.name:
        refs.add(expression.name)
        return
    if expression.kind == "param_lookup":
        for value in (expression.key or {}).values():
            _collect_scalar_input_refs(value, refs)
        return
    if expression.kind == "binary":
        for value in (expression.left, expression.right):
            if value is not None:
                _collect_scalar_input_refs(value, refs)
        return
    if expression.kind == "case":
        for branch in expression.cases or ():
            _collect_scalar_input_refs(branch.condition, refs)
            _collect_scalar_input_refs(branch.value, refs)
        if expression.fallback is not None:
            _collect_scalar_input_refs(expression.fallback, refs)


def _collect_relation_input_refs(expression: RelationExpr, refs: set[str]) -> None:
    if expression.kind == "input" and expression.name:
        refs.add(expression.name)
    for source in (expression.source, expression.left, expression.right):
        if source is not None:
            _collect_relation_input_refs(source, refs)
    for column in (expression.columns or {}).values():
        if column.scalar is not None:
            _collect_scalar_input_refs(column.scalar, refs)
        if column.series is not None:
            _collect_value_input_refs(column.series, refs)
        if column.relation is not None:
            _collect_relation_input_refs(column.relation, refs)
    if expression.condition is not None:
        _collect_scalar_input_refs(expression.condition, refs)
    for value in (expression.new_columns or {}).values():
        _collect_scalar_input_refs(value, refs)


def _compute_node_input(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
) -> ComputeNodeInput:
    if isinstance(value, ComputeResultRef):
        return ComputeNodeInput(kind="compute_result", node_id=value.node_id)
    if isinstance(value, RouteBindingRef):
        return ComputeNodeInput(kind="route", port_id=value.port_id)
    expression = _literal_data_expr(value)
    source_inputs = _value_input_refs(expression)
    bound = _bind_value_input_refs(expression, inputs)
    return ComputeNodeInput(
        kind="value",
        value=as_value_expr(bound),
        source_inputs=list(source_inputs),
    )


def _state_specs(
    bindings: Sequence[BindingSpec],
    *,
    inputs: Mapping[str, object],
) -> list[StateSpec]:
    specs: list[StateSpec] = []
    for binding in bindings:
        value = binding.value
        specs.append(
            set_state(
                binding.resource_id,
                f"{binding.capability_id}.{binding.field_path}",
                (
                    value
                    if isinstance(value, ComputeResultRef)
                    else _bind_input_refs(_expr_to_scalar(value), inputs)
                ),
            )
        )
    return specs


def _state_scalar_expr(value: object) -> ScalarExpr:
    if isinstance(value, Expression):
        return _expr_to_scalar(value)
    return as_scalar_expr(value)


def _state_value_expr(value: object) -> ScalarExpr | ComputeResultRef:
    if isinstance(value, ComputeResultRef):
        return value
    return _state_scalar_expr(value)


def _bind_state_value(
    value: ScalarExpr | ComputeResultRef,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
) -> ScalarExpr | ComputeResultRef:
    if isinstance(value, ComputeResultRef):
        return value
    return _bind_input_refs(value, inputs, unbound_to_outer=unbound_to_outer)


def _state_route_expr(value: object) -> StateRouteExpr:
    if isinstance(value, Expression):
        return _expr_to_scalar(value)
    if isinstance(value, ScalarExpr | SeriesExpr):
        return value
    if isinstance(value, RelationExpr):
        msg = "state route entity source must be scalar or series-shaped"
        raise TypeError(msg)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return values([_input_cell(item) for item in cast("Sequence[object]", value)])
    return as_scalar_expr(value)


def _bind_state_route_expr(
    ctx: ExperimentAuthoringContext,
    expression: StateRouteExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
) -> StateRouteExpr:
    bound = _bind_value_input_refs(
        expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
    )
    if isinstance(bound, RelationExpr):
        ctx.raise_diagnostic(
            "module_state_route_entity_invalid",
            "state route entity source must be scalar or series-shaped",
            "state.route_entities",
        )
    return bound


def _substitute_state_route_expr(
    expression: StateRouteExpr,
    inputs: Mapping[str, object],
) -> StateRouteExpr:
    substituted = _substitute_value_input_refs(expression, inputs)
    if isinstance(substituted, RelationExpr):
        msg = "state route entity source must be scalar or series-shaped"
        raise TypeError(msg)
    return substituted


def _state_field_capability(
    ctx: ExperimentAuthoringContext,
    field: str,
) -> str:
    capability_id, separator, field_path = field.partition(".")
    if not separator or not capability_id or not field_path:
        ctx.raise_diagnostic(
            "module_state_field_invalid",
            "state field must use 'capability.field' syntax",
            "state.field",
        )
    return capability_id


def _expr_to_scalar(expression: Expression | ScalarExpr) -> ScalarExpr:
    if isinstance(expression, ScalarExpr):
        return expression
    if expression.kind == "quantity":
        return _literal(_required_quantity(expression.quantity, "expression.quantity"))
    if expression.kind == "number":
        return _literal(_required_float(expression.value, "expression.value"))
    if expression.kind == "variable":
        return col(_required_name(expression.name, "expression.name"))
    if expression.kind == "parameter":
        return param(_required_name(expression.name, "expression.name"))
    if expression.kind == "binary":
        return ScalarExpr(
            kind="binary",
            op=expression.op,
            left=_expr_to_scalar(
                _required_expression(expression.left, "expression.left")
            ),
            right=_expr_to_scalar(
                _required_expression(expression.right, "expression.right")
            ),
        )
    msg = f"unsupported expression kind: {expression.kind}"
    raise ValueError(msg)


def _static_positive_int(
    ctx: ExperimentAuthoringContext,
    value: Expression | ScalarExpr | Quantity | float | None,
    *,
    default: int,
    path: str,
    inputs: Mapping[str, object],
) -> int:
    if value is None:
        return default
    expression = (
        value
        if isinstance(value, Expression | ScalarExpr)
        else Expression.from_value(value)
    )
    try:
        evaluated = _expr_to_scalar(expression).eval(
            EvalContext(params=_relation_params(ctx), inputs=_input_row(inputs))
        )
    except Exception as error:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            f"records value must resolve from config at authoring time: {error}",
            path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            "records value must resolve to a numeric count",
            path,
        )
    if number <= 0 or int(number) != number:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            "records value must be a positive integer",
            path,
        )
    return int(number)


def _static_axis_size(
    ctx: ExperimentAuthoringContext,
    value: AxisSizeInput | None,
    *,
    default: int,
    path: str,
    inputs: Mapping[str, object],
    entity_axis: bool = False,
) -> tuple[int, dict[str, Any]]:
    if isinstance(value, SeriesExpr):
        evaluated = _bind_series_input_refs(value, inputs).evaluate(
            EvalContext(params=_relation_params(ctx), inputs=_input_values(inputs))
        )
        if not entity_axis:
            return len(evaluated), {}
        entities = _axis_entities(
            ctx,
            evaluated,
            path=path,
        )
        return len(entities), _entity_axis_metadata(entities)
    if isinstance(value, RelationExpr):
        if entity_axis:
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                "entity record axis must be scalar or series-shaped",
                path,
            )
        evaluated_rows = _bind_relation_input_refs(value, inputs).evaluate(
            _relation_params(ctx),
            inputs=_input_values(inputs),
        )
        return len(evaluated_rows), {}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        if not entity_axis:
            return len(value), {}
        entities = _axis_entities(
            ctx,
            cast("Sequence[object]", value),
            path=path,
        )
        return len(entities), _entity_axis_metadata(entities)
    if entity_axis:
        if not isinstance(value, Expression | ScalarExpr):
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                "entity record axis must resolve to an entity series",
                path,
            )
        try:
            evaluated_entity = _expr_to_scalar(value).eval(
                EvalContext(params=_relation_params(ctx), inputs=_input_row(inputs))
            )
        except Exception as error:
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                f"entity record axis could not be evaluated: {error}",
                path,
            )
        entities = _axis_entities(
            ctx,
            [evaluated_entity],
            path=path,
        )
        return len(entities), _entity_axis_metadata(entities)
    if not isinstance(value, Expression | ScalarExpr) and value is not None:
        _validate_axis_size_literal(value)
    positive_value = cast(
        "Expression | ScalarExpr | Quantity | float | None",
        value,
    )
    return (
        _static_positive_int(
            ctx,
            positive_value,
            default=default,
            path=path,
            inputs=inputs,
        ),
        {},
    )


def _validate_axis_size_literal(value: AxisSizeInput) -> None:
    if isinstance(value, Quantity | int | float) and not isinstance(value, bool):
        return
    msg = f"axis size must be numeric or an entity series, got {value!r}"
    raise TypeError(msg)


def _axis_entities(
    ctx: ExperimentAuthoringContext,
    values: Sequence[object],
    *,
    path: str,
) -> tuple[EntityRef, ...]:
    if not values:
        ctx.raise_diagnostic(
            "module_record_entity_axis_invalid",
            "entity record axis must not be empty",
            path,
        )
    if not all(isinstance(value, EntityRef | str) and bool(value) for value in values):
        ctx.raise_diagnostic(
            "module_record_entity_axis_invalid",
            "entity record axis values must be entity references",
            path,
        )
    resolved = ctx.require_entities(cast("Sequence[EntityRef | str]", values))
    entity_ids = [entity.id for entity in resolved]
    duplicates = sorted(
        entity_id for entity_id, count in Counter(entity_ids).items() if count > 1
    )
    if duplicates:
        ctx.raise_diagnostic(
            "module_record_entity_axis_duplicate",
            "entity record axis contains duplicate entities: " + ", ".join(duplicates),
            path,
        )
    return resolved


def _entity_axis_metadata(value: Sequence[EntityRef]) -> dict[str, Any]:
    entity_kind = value[0].kind if value else None
    if entity_kind is None or any(entity.kind != entity_kind for entity in value):
        entity_kind = None
    return {
        "entities": [entity.model_dump(mode="json") for entity in value],
        **({"entity_kind": entity_kind} if entity_kind else {}),
    }


def _relation_params(ctx: ExperimentAuthoringContext) -> ParameterRelationData:
    return ParameterRelationData.from_parameter_view(ctx.parameter_view)


def _input_row(inputs: Mapping[str, object]) -> dict[str, CellValue]:
    row: dict[str, CellValue] = {}
    for key, value in inputs.items():
        try:
            row[key] = _input_cell(value)
        except TypeError:
            continue
    return row


def _input_values(inputs: Mapping[str, object]) -> dict[str, object]:
    return dict(inputs)


def _input_cell(value: object) -> CellValue:
    if (
        isinstance(
            value,
            Quantity | EntityRef | PayloadValue | str | int | float | bool,
        )
        or value is None
    ):
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if not all(isinstance(key, str) for key in mapping):
            msg = "record input keys must be strings"
            raise TypeError(msg)
        return cast("dict[str, Any]", dict(mapping))
    msg = f"input value is not available as a scalar expression value: {value!r}"
    raise TypeError(msg)


def _module_parameter_derivations(
    module_id: str,
    derivations: ParameterDerivationInput,
) -> ParameterDerivationSet | None:
    if derivations is None or isinstance(derivations, ParameterDerivationSet):
        return derivations
    return _combined_parameter_derivations(
        id=f"{module_id}.parameter_derivations",
        derivations=tuple(derivations),
    )


def _combined_parameter_derivations(
    *,
    id: str,  # noqa: A002
    derivations: Sequence[ParameterDerivationSet | None],
) -> ParameterDerivationSet | None:
    selected: list[ParameterDerivationSet] = []
    seen_ids: set[str] = set()
    for derivation in derivations:
        if derivation is None or derivation.id in seen_ids:
            continue
        selected.append(derivation)
        seen_ids.add(derivation.id)
    return combine_parameter_derivations(id=id, derivations=selected)


def _literal(value: CellValue) -> ScalarExpr:
    return ScalarExpr(kind="literal", value=value)


def _required_quantity(value: Quantity | None, path: str) -> Quantity:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_quantities(value: list[Quantity] | None, path: str) -> list[Quantity]:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_expression(value: Expression | None, path: str) -> Expression:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_scalar(value: ScalarExpr | None, path: str) -> ScalarExpr:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_int(value: int | None, path: str) -> int:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_float(value: float | None, path: str) -> float:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_name(value: str | None, path: str) -> str:
    if not value:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


__all__ = [
    "BindingIntent",
    "ComputeNodeIntent",
    "ComputeResultRef",
    "DerivedVariableIntent",
    "ExperimentBindingIntent",
    "ExperimentModule",
    "ExperimentStateIntent",
    "ExplicitVariableIntent",
    "ModuleBuilder",
    "ModuleInputPort",
    "ModuleInvocation",
    "ModuleProductPort",
    "ProductSelectionIntent",
    "RecordAxisIntent",
    "RecordIntent",
    "ResourcePort",
    "ResourceSelector",
    "RouteBindingRef",
    "StateEachIntent",
    "VariableIntent",
    "bind",
    "bind_value_input_refs",
    "compute_result",
    "derive",
    "entity_axis",
    "input_ref",
    "input_series",
    "input_table",
    "module",
    "observable",
    "param_ref",
    "record_axis",
    "record_product",
    "requires",
    "resource_port",
    "route",
    "shot_axis",
    "var_ref",
    "variable",
]
