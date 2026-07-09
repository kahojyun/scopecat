"""Module-based experiment assembly from structured authoring inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from scopecat._planning.parameter_patches import ParameterPatchSpec
from scopecat.authoring._bindings import (
    BindingIntent,
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    bind,
    build_route_intents,
    ports_by_id,
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
from scopecat.experiments import (
    ComputeNodeFunction,
    ComputeNodeInput,
    ComputeNodeSpec,
    ExperimentSpec,
    RecordAxisSpec,
    RecordKind,
    RecordSource,
    RecordSpec,
    StateSpec,
    bind_each,
    set_state,
)
from scopecat.experiments import (
    record_axis as experiment_record_axis,
)
from scopecat.models.entity import EntityArray, EntityRef, entity_array
from scopecat.models.parameter import Quantity
from scopecat.parameters import ParameterDerivationSet, combine_parameter_derivations
from scopecat.relations import (
    CaseBranch,
    CellValue,
    EvalContext,
    ParameterRelationData,
    RelationExpr,
    Row,
    ScalarExpr,
    col,
    grid,
    literal_rows,
    param,
    range_values,
    table,
    values,
)
from scopecat.relations import (
    input_ref as relation_input_ref,
)
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
type AxisSizeInput = (
    Expression | ScalarExpr | Quantity | float | EntityArray | Sequence[EntityRef | str]
)
type ComputeNodeInputValue = (
    Expression | ScalarExpr | Quantity | float | ComputeResultRef | RouteBindingRef
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
class StateTableIntent:
    table_id: str
    field: str
    value_column: str
    resource_column: str = "resource_id"
    resource_port: str | None = None
    route_entity_column: str | None = None

    def build(self) -> StateSpec:
        return bind_each(
            table(self.table_id),
            set_state(
                self.resource_port or col(self.resource_column),
                self.field,
                col(self.value_column),
                route_entities=(
                    [col(self.route_entity_column)]
                    if self.route_entity_column is not None
                    else []
                ),
            ),
        )


ExperimentStateIntent = StateTableIntent


@dataclass(frozen=True)
class ComputeResultRef:
    node_id: str


@dataclass(frozen=True)
class RouteBindingRef:
    port_id: str


@dataclass(frozen=True)
class ComputeNodeIntent:
    id: str
    fn: ComputeNodeFunction
    inputs: tuple[tuple[str, ComputeNodeInputValue], ...] = ()
    route_ports: tuple[str, ...] = ()

    def build(self, inputs: Mapping[str, object]) -> ComputeNodeSpec:
        return ComputeNodeSpec(
            id=self.id,
            inputs={
                name: _compute_node_input(value, inputs) for name, value in self.inputs
            },
            route_ports=list(self.route_ports),
            fn=self.fn,
        )


@dataclass(frozen=True)
class ModuleInputPort:
    id: str
    kind: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _entity_input_ids(input_ports: Sequence[ModuleInputPort]) -> tuple[str, ...]:
    return tuple(port.id for port in input_ports if port.kind == "entity")


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
                        kind="entity",
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
        kind: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ModuleBuilder:
        return replace(
            self,
            input_ports=(
                *self.input_ports,
                ModuleInputPort(id=id, kind=kind, metadata=dict(metadata or {})),
            ),
        )

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: ResourceSelector | Sequence[str] = (),
        for_entities: Sequence[str] = (),
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
        value: Expression | ScalarExpr | Quantity | float,
    ) -> ModuleBuilder:
        return replace(self, bindings=(*self.bindings, bind(port_path, value)))

    def state_table(
        self,
        table_id: str,
        *,
        field: str,
        value_column: str,
        resource_column: str = "resource_id",
        resource_port: str | None = None,
        route_entity_column: str | None = None,
    ) -> ModuleBuilder:
        return replace(
            self,
            state_intents=(
                *self.state_intents,
                StateTableIntent(
                    table_id=table_id,
                    field=field,
                    value_column=value_column,
                    resource_column=resource_column,
                    resource_port=resource_port,
                    route_entity_column=route_entity_column,
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
                ),
            ),
        )

    def bind_compute(
        self,
        port_path: str,
        node_id: str,
        *,
        kind: str,
    ) -> ModuleBuilder:
        return replace(
            self,
            bindings=(
                *self.bindings,
                bind(port_path, _compute_result_state_value(node_id, kind=kind)),
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
) -> dict[str, object]:
    return {
        input_id: _module_invocation_input_expr(value, parent_inputs)
        for input_id, value in invocation.inputs.items()
    }


def _localize_module_invocation_assembly(
    invocation: ModuleInvocation,
    parent_inputs: Mapping[str, object],
    *,
    source_index: int,
) -> ExperimentAssembly:
    local_inputs = _module_invocation_inputs(invocation, parent_inputs)
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
        entity_inputs: list[str] = []
        for input_id in port.selector.entity_inputs:
            value = inputs.get(input_id)
            if not isinstance(value, ScalarExpr):
                entity_inputs.append(input_id)
                continue
            if value.kind == "column":
                entity_inputs.append(_required_name(value.name, "column.name"))
                continue
            if value.kind == "literal":
                hidden_id = f"__local_entity_{source_index}_{input_id}"
                entity_inputs.append(hidden_id)
                hidden_inputs[hidden_id] = value.value
                continue
            msg = (
                f"module invocation entity input {input_id!r} must bind to a "
                "literal entity or parent input"
            )
            raise ValueError(msg)
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
) -> ScalarExpr:
    if isinstance(value, ScalarExpr):
        return _bind_input_refs(value, parent_inputs)
    if isinstance(value, Expression):
        return _bind_input_refs(_expr_to_scalar(value), parent_inputs)
    return _literal(_input_cell(value))


def _localize_binding_input_refs(
    binding: ExperimentBindingIntent,
    inputs: Mapping[str, object],
) -> ExperimentBindingIntent:
    expression = (
        binding.value
        if isinstance(binding.value, Expression | ScalarExpr)
        else Expression.from_value(binding.value)
    )
    return replace(
        binding,
        value=_substitute_input_refs(_expr_to_scalar(expression), inputs),
    )


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
    if isinstance(value, Expression | ScalarExpr):
        return _substitute_input_refs(_expr_to_scalar(value), inputs)
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
    if not isinstance(axis.size, Expression | ScalarExpr):
        return axis
    return replace(
        axis,
        size=_substitute_input_refs(_expr_to_scalar(axis.size), inputs),
    )


def _substitute_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        value = inputs.get(input_name)
        return value if isinstance(value, ScalarExpr) else expression
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _substitute_input_refs(value, inputs)
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
                ),
                "right": _substitute_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
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
                            ),
                            "value": _substitute_input_refs(branch.value, inputs),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _substitute_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                ),
            }
        )
    return expression


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


def compute_result(node_id: str) -> ComputeResultRef:
    return ComputeResultRef(node_id=node_id)


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
    entities: Expression | ScalarExpr | EntityArray | Sequence[EntityRef | str],
) -> RecordAxisIntent:
    return record_axis(
        id,
        size=entities,
        kind="entity",
        unit=None,
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


def _resolve_entity_inputs(
    ctx: ExperimentAuthoringContext,
    entity_inputs: tuple[str, ...],
    inputs: Mapping[str, object],
) -> list[EntityRef | EntityArray]:
    entities: list[EntityRef | EntityArray] = []
    for input_id in entity_inputs:
        if input_id not in inputs:
            continue
        value = inputs.get(input_id)
        if isinstance(value, str) and value:
            entities.append(ctx.require_entity(value))
            continue
        if isinstance(value, EntityRef):
            entities.append(ctx.require_entity(value))
            continue
        if isinstance(value, EntityArray):
            entities.append(ctx.require_entity_array(value))
            continue
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            selected = entity_array(cast("Sequence[EntityRef | str]", value))
            entities.append(ctx.require_entity_array(selected))
            continue
        if not value:
            ctx.raise_diagnostic(
                "module_entity_input_invalid",
                f"module entity input {input_id} must be an entity or entity array",
                input_id,
            )
        ctx.raise_diagnostic(
            "module_entity_input_invalid",
            f"module entity input {input_id} must be an entity or entity array",
            input_id,
        )
    return entities


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
    _resolve_entity_inputs(ctx, assembly.entity_inputs, assembly.inputs)
    resource_ports = ports_by_id(ctx, assembly.resource_ports)
    route_intents = build_route_intents(
        ctx,
        assembly.resource_ports,
        inputs=assembly.inputs,
    )
    variables = {
        intent.variable_id: intent.build(ctx, assembly.inputs)
        for intent in assembly.variables
    }
    bindings = [binding.build(ctx, resource_ports) for binding in assembly.bindings]
    points = _points_relation(
        ctx,
        _build_point_source(assembly.point_source, assembly.inputs),
        variables,
        inputs=assembly.inputs,
        entity_input_ids=assembly.entity_inputs,
    )
    records = [
        *_lower_records(ctx, assembly.records, assembly.inputs),
        *_lower_product_selections(
            ctx,
            assembly.record_selections,
            assembly.product_ports,
            assembly.inputs,
        ),
    ]
    return ExperimentSpec(
        id=assembly.experiment_id,
        kind=assembly.kind,
        points=points,
        route_intents=route_intents,
        compute_nodes=[node.build(assembly.inputs) for node in assembly.compute_nodes],
        params=list(assembly.params),
        state=[
            *_state_specs(bindings, inputs=assembly.inputs),
            *(intent.build() for intent in assembly.state_intents),
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
            dict.fromkeys(
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
    return literal_rows(
        _resolve_point_entities(
            ctx,
            relation.evaluate(
                ctx.parameter_view,
                inputs=_input_row(inputs),
            ),
            entity_input_ids=entity_input_ids,
        )
    )


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
    if isinstance(value, EntityArray):
        return ctx.require_entity_array(value)
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
) -> ScalarExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return col(input_name)
        value = inputs[input_name]
        if isinstance(value, ScalarExpr):
            return value
        if isinstance(value, Expression):
            return _expr_to_scalar(value)
        return _literal(_input_cell(value))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _bind_input_refs(value, inputs)
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
                ),
                "right": _bind_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": _bind_input_refs(branch.condition, inputs),
                            "value": _bind_input_refs(branch.value, inputs),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _bind_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                ),
            }
        )
    return expression


def bind_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    return _bind_input_refs(expression, inputs)


def _bind_input_refs_with_provenance(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> tuple[ScalarExpr, tuple[str, ...]]:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return col(input_name), (input_name,)
        value = inputs[input_name]
        if isinstance(value, ScalarExpr):
            return value, (input_name,)
        if isinstance(value, Expression):
            return _expr_to_scalar(value), (input_name,)
        return _literal(_input_cell(value)), (input_name,)
    if expression.kind == "param_lookup":
        bound_keys: dict[str, ScalarExpr] = {}
        param_source_inputs: list[str] = []
        for name, value in (expression.key or {}).items():
            bound, child_inputs = _bind_input_refs_with_provenance(value, inputs)
            bound_keys[name] = bound
            param_source_inputs.extend(child_inputs)
        return expression.model_copy(update={"key": bound_keys}), tuple(
            sorted(set(param_source_inputs))
        )
    if expression.kind == "binary":
        left, left_inputs = _bind_input_refs_with_provenance(
            _required_scalar(expression.left, "expression.left"),
            inputs,
        )
        right, right_inputs = _bind_input_refs_with_provenance(
            _required_scalar(expression.right, "expression.right"),
            inputs,
        )
        return (
            expression.model_copy(update={"left": left, "right": right}),
            tuple(sorted({*left_inputs, *right_inputs})),
        )
    if expression.kind == "case":
        case_source_inputs: list[str] = []
        cases: list[CaseBranch] = []
        for branch in expression.cases or []:
            condition, condition_inputs = _bind_input_refs_with_provenance(
                branch.condition,
                inputs,
            )
            value, value_inputs = _bind_input_refs_with_provenance(
                branch.value,
                inputs,
            )
            case_source_inputs.extend((*condition_inputs, *value_inputs))
            cases.append(
                branch.model_copy(update={"condition": condition, "value": value})
            )
        fallback, fallback_inputs = _bind_input_refs_with_provenance(
            _required_scalar(expression.fallback, "expression.fallback"),
            inputs,
        )
        case_source_inputs.extend(fallback_inputs)
        return (
            expression.model_copy(update={"cases": cases, "fallback": fallback}),
            tuple(sorted(set(case_source_inputs))),
        )
    return expression, ()


def _compute_node_input(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
) -> ComputeNodeInput:
    if isinstance(value, ComputeResultRef):
        return ComputeNodeInput(kind="compute_result", node_id=value.node_id)
    if isinstance(value, RouteBindingRef):
        return ComputeNodeInput(kind="route", port_id=value.port_id)
    expression = (
        value
        if isinstance(value, Expression | ScalarExpr)
        else Expression.from_value(value)
    )
    bound, source_inputs = _bind_input_refs_with_provenance(
        _expr_to_scalar(expression),
        inputs,
    )
    return ComputeNodeInput(
        kind="value",
        value=bound,
        source_inputs=list(source_inputs),
    )


def _state_specs(
    bindings: Sequence[BindingSpec],
    *,
    inputs: Mapping[str, object],
) -> list[StateSpec]:
    return [
        set_state(
            binding.resource_id,
            f"{binding.capability_id}.{binding.field_path}",
            _bind_input_refs(_expr_to_scalar(binding.value), inputs),
        )
        for binding in bindings
    ]


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
) -> tuple[int, dict[str, Any]]:
    if isinstance(value, EntityArray):
        entities = ctx.require_entity_array(value)
        return entities.size, _entity_axis_metadata(entities)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        try:
            entities = entity_array(value)
        except Exception:
            entities = None
        if entities is not None:
            entities = ctx.require_entity_array(entities)
            return entities.size, _entity_axis_metadata(entities)
    expression = (
        value
        if isinstance(value, Expression | ScalarExpr) or value is None
        else _axis_size_expression(value)
    )
    if expression is not None:
        try:
            evaluated = _expr_to_scalar(expression).eval(
                EvalContext(params=_relation_params(ctx), inputs=_input_row(inputs))
            )
        except Exception:
            evaluated = None
        if isinstance(evaluated, EntityArray):
            entities = ctx.require_entity_array(evaluated)
            return entities.size, _entity_axis_metadata(entities)
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


def _axis_size_expression(value: AxisSizeInput) -> Expression:
    if isinstance(value, Quantity | int | float) and not isinstance(value, bool):
        return Expression.from_value(value)
    msg = f"axis size must be numeric or an entity array, got {value!r}"
    raise TypeError(msg)


def _entity_axis_metadata(value: EntityArray) -> dict[str, Any]:
    return {
        "entities": [entity.model_dump(mode="json") for entity in value.entities],
        **({"entity_kind": value.kind} if value.kind else {}),
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


def _input_cell(value: object) -> CellValue:
    if (
        isinstance(value, Quantity | EntityRef | EntityArray | str | int | float | bool)
        or value is None
    ):
        return value
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


def _compute_result_state_value(node_id: str, *, kind: str) -> ScalarExpr:
    return _literal(
        {
            "kind": "compute_result",
            "node_id": node_id,
            "payload_kind": kind,
        }
    )


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
    "StateTableIntent",
    "VariableIntent",
    "bind",
    "compute_result",
    "derive",
    "entity_axis",
    "input_ref",
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
