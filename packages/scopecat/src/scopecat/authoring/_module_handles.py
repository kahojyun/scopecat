"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, TypeGuard, cast, override

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    resource_port,
)
from scopecat.authoring._binding_intents import (
    bind_field as binding_field,
)
from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_module_inputs,
    freeze_runtime_input,
)
from scopecat.authoring._intents import (
    ClosedScalarValue,
    ExperimentStateIntent,
    ModuleActionDecl,
    ModuleInputPort,
    ModuleOperationDecl,
    StateEachIntent,
    StateRouteValue,
)
from scopecat.authoring._module_ir import (
    InvocationKey,
    ModuleAcquireEffect,
    ModuleActionEffect,
    ModuleBindingEffect,
    ModuleDomainEffect,
    ModuleEffectIR,
    ModuleInstanceEffect,
    ModuleIR,
    ModuleParallelEffect,
    ModulePythonImplementation,
    ModuleStateEffect,
    ModuleValueExport,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
    ProductAxis,
    ProductOutputs,
    ProductRef,
)
from scopecat.authoring._value_refs import (
    TableRow,
    ValueDeclarationKey,
    ValueRef,
    internal_literal_value_ref,
    internal_module_export_value_ref,
    internal_value_ref_input_id,
    internal_value_ref_operation_id,
)
from scopecat.authoring.domain import DomainExecution
from scopecat.authoring.measurements import MeasurementTransform
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
from scopecat.compiler.relations.model import RowScopeId
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.measurements.results import MeasurementDType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

if TYPE_CHECKING:
    from scopecat.authoring.templates import TemplateBuilder


type StateLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type BindingInput = StateLiteral | ValueRef
type StateRowValue = Callable[[TableRow], ValueRef]
type StateScalarInput = BindingInput | StateRowValue
type StateRouteInput = StateScalarInput | Sequence[StateLiteral]


def _empty_resource_bindings() -> FrozenMapping[
    LogicalResourcePortId, LogicalResourcePortId
]:
    return FrozenMapping()


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


def _resource_capabilities(requires: tuple[str, ...]) -> tuple[str, ...]:
    if any(not capability for capability in requires):
        msg = "resource capability ids must be non-empty"
        raise ValueError(msg)
    return requires


@dataclass(frozen=True, slots=True, repr=False)
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
    output_ports: tuple[ModuleValueExport, ...] = ()
    resources: tuple[ResourcePort, ...] = ()
    procedure: tuple[ModuleEffectIR, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    measurement_transform_intents: tuple[MeasurementTransform, ...] = ()
    product_declarations: tuple[ModuleProductDecl, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    @property
    def observables(self) -> tuple[str, ...]:
        return tuple(
            product.qualified_id
            for product in self.product_declarations
            if product.kind == "observable"
        )

    @property
    def products(self) -> ProductOutputs:
        """Stable references to products declared on this builder so far."""

        return ProductOutputs(
            {
                product.qualified_id: ProductRef(
                    product_id=product.product_id,
                    origin=product.origin,
                )
                for product in self.product_declarations
            }
        )

    @property
    def has_content(self) -> bool:
        """Whether this builder contributes declarations or procedure effects."""

        return any(
            (
                self.resources,
                self.invocations,
                self.input_ports,
                self.output_ports,
                self.procedure,
                self.operations,
                self.python_implementations,
                self.measurement_transform_intents,
                self.product_declarations,
            )
        )

    def use(
        self,
        *modules: ModuleInvocation,
    ) -> ModuleBuilder:
        from scopecat.authoring._module_construction import module_use_invocation

        invocations = tuple(module_use_invocation(module) for module in modules)
        combined = (*self.invocations, *invocations)
        invocation_scopes = tuple(
            invocation.instance_id or f"{invocation.module.id}[{index}]"
            for index, invocation in enumerate(combined)
        )
        duplicates = sorted(
            scope
            for scope in set(invocation_scopes)
            if invocation_scopes.count(scope) > 1
        )
        if duplicates:
            duplicate_list = ", ".join(repr(scope) for scope in duplicates)
            msg = f"module builder has duplicate instance ids: {duplicate_list}"
            raise ValueError(msg)
        return replace(
            self,
            invocations=combined,
            procedure=(
                *self.procedure,
                *(ModuleInstanceEffect(item.invocation_key) for item in invocations),
            ),
        )

    def sequence(self, *modules: ModuleInvocation) -> ModuleBuilder:
        """Append child procedures in deterministic sequence."""

        return self.use(*modules)

    def parallel(self, *modules: ModuleInvocation) -> ModuleBuilder:
        """Append child procedures as a may-run-in-parallel group.

        The scheduler may serialize branches when concrete resource claims
        conflict. Explicit bindings to the same parent resource are rejected
        at definition time because they are never independent.
        """

        if len(modules) < 2:
            raise ValueError("parallel requires at least two module invocations")
        from scopecat.authoring._module_construction import module_use_invocation

        invocations = tuple(module_use_invocation(module) for module in modules)
        combined = (*self.invocations, *invocations)
        instance_ids = tuple(item.instance_id for item in combined)
        duplicates = sorted(
            item for item in set(instance_ids) if instance_ids.count(item) > 1
        )
        if duplicates:
            raise ValueError(
                "module builder has duplicate instance ids: "
                + ", ".join(repr(item) for item in duplicates)
            )
        return replace(
            self,
            invocations=combined,
            procedure=(
                *self.procedure,
                ModuleParallelEffect(
                    tuple(item.invocation_key for item in invocations)
                ),
            ),
        )

    @property
    def bindings(self) -> tuple[ExperimentBindingIntent, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleBindingEffect)
        )

    @property
    def state_intents(self) -> tuple[ExperimentStateIntent, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleStateEffect)
        )

    @property
    def actions(self) -> tuple[ModuleActionDecl, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleActionEffect)
        )

    @property
    def domain_executions(self) -> tuple[DomainExecution, ...]:
        return tuple(
            effect.execution
            for effect in self.procedure
            if isinstance(effect, ModuleDomainEffect)
        )

    @property
    def acquisitions(self) -> tuple[ModuleAcquireEffect, ...]:
        return tuple(
            effect
            for effect in self.procedure
            if isinstance(effect, ModuleAcquireEffect)
        )

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
        return replace(self, input_ports=(*self.input_ports, *ports))

    def export(self, **values: ValueRef) -> ModuleBuilder:
        """Export named typed values from each future module instance.

        Exports are value edges for composition, not persisted measurement
        products.  Instantiate the built module to obtain instance-owned
        references through ``invocation.outputs``.
        """

        existing = {port.id for port in self.output_ports}
        ports: list[ModuleValueExport] = []
        for output_id, value in values.items():
            if not output_id:
                msg = "module output ids must be non-empty"
                raise ValueError(msg)
            if output_id in existing:
                msg = f"module output {output_id!r} is already declared"
                raise ValueError(msg)
            existing.add(output_id)
            ports.append(
                ModuleValueExport(
                    id=output_id,
                    source=value,
                )
            )
        return replace(self, output_ports=(*self.output_ports, *ports))

    def resource(
        self,
        id: str,  # noqa: A002
        *,
        requires: tuple[str, ...] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> ModuleBuilder:
        capabilities = _resource_capabilities(requires)
        for value in for_entities:
            if not _is_entity_input_type(value.value_type):
                msg = "resource for_entities values must be entity-shaped"
                raise TypeError(msg)
            if internal_value_ref_operation_id(value) is not None:
                msg = "resource for_entities cannot use compute outputs"
                raise TypeError(msg)
        selector = ResourceSelector(
            capabilities=capabilities,
            entity_inputs=tuple(for_entities),
        )
        return replace(
            self,
            resources=(
                *self.resources,
                resource_port(id, selector),
            ),
        )

    def bind_field(
        self,
        resource: str,
        *,
        capability: str,
        field: str,
        value: BindingInput,
    ) -> ModuleBuilder:
        """Bind state through structured resource/capability/field identities."""

        if not _is_public_binding_input(value):
            msg = "module bindings require a typed value or scalar literal"
            raise TypeError(msg)
        return replace(
            self,
            procedure=(
                *self.procedure,
                ModuleBindingEffect(
                    binding_field(
                        resource,
                        capability=capability,
                        field=field,
                        value=cast("BindingInput", _capture_state_literal(value)),
                    )
                ),
            ),
        )

    def state_each(
        self,
        relation: ValueRef,
        *,
        resource: StateScalarInput | None = None,
        resource_port: str | None = None,
        capability: str,
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
        declaration_key = ValueDeclarationKey.fresh()
        row_scope_id = RowScopeId(
            SymbolId(local_id=f"state_row_{declaration_key.value.hex}")
        )
        row = TableRow(
            relation,
            scope_id=row_scope_id,
        )
        if not capability or not field:
            msg = "state capability and field ids must be non-empty"
            raise ValueError(msg)
        return replace(
            self,
            procedure=(
                *self.procedure,
                ModuleStateEffect(
                    StateEachIntent(
                        relation=relation,
                        row_scope_id=row_scope_id,
                        resource=_state_scalar_expr(
                            _resolve_state_row_value(
                                resource,
                                row,
                                path="state_each.resource",
                            )
                        ),
                        capability_id=capability,
                        field_path=field,
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
                        resource_port=(
                            logical_resource_port_id(resource_port)
                            if resource_port is not None
                            else None
                        ),
                    )
                ),
            ),
        )

    def action(
        self,
        id: str,  # noqa: A002
        *,
        resource: str,
        capability: str,
        fields: Mapping[str, BindingInput] | None = None,
    ) -> ModuleBuilder:
        """Invoke one receipt-bearing instrument action for every point.

        Actions are ordered effects, not desired state: identical invocations
        at adjacent points are both delivered to the driver.
        """

        if not id or not resource or not capability:
            msg = "action, resource, and capability ids must be non-empty"
            raise ValueError(msg)
        if id in {action.id for action in self.actions}:
            msg = f"module action {id!r} is already declared"
            raise ValueError(msg)
        selected_fields = dict(fields or {})
        invalid = sorted(
            name
            for name, value in selected_fields.items()
            if not name or not _is_public_binding_input(value)
        )
        if invalid:
            msg = "action fields require non-empty ids and typed or scalar values"
            raise TypeError(msg)
        return replace(
            self,
            procedure=(
                *self.procedure,
                ModuleActionEffect(
                    ModuleActionDecl(
                        id=id,
                        resource_port_id=logical_resource_port_id(resource),
                        capability_id=capability,
                        fields=tuple(
                            (name, cast("BindingInput", _capture_state_literal(value)))
                            for name, value in selected_fields.items()
                        ),
                    )
                ),
            ),
        )

    def domain(self, execution: DomainExecution) -> ModuleBuilder:
        """Append one opaque domain-program effect to this module procedure."""

        if execution.id in {item.id for item in self.domain_executions}:
            raise ValueError(f"domain execution id {execution.id!r} is repeated")
        return replace(
            self,
            procedure=(*self.procedure, ModuleDomainEffect(execution)),
        )

    def acquire(
        self,
        id: str,  # noqa: A002
        *products: str | ProductRef,
    ) -> ModuleBuilder:
        """Acquire instrument products at this exact procedure position."""

        if not id or not products:
            raise ValueError("acquire requires a non-empty id and products")
        if id in {effect.id for effect in self.acquisitions}:
            raise ValueError(f"module acquisition {id!r} is already declared")
        selected = tuple(
            self.products[product] if isinstance(product, str) else product
            for product in products
        )
        return replace(
            self,
            procedure=(*self.procedure, ModuleAcquireEffect(id, selected)),
        )

    def computes(self, *definitions: Compute) -> ModuleBuilder:
        """Register typed compute declarations and their output values."""

        existing = {operation.id for operation in self.operations}
        operations: list[ModuleOperationDecl] = []
        implementations: list[ModulePythonImplementation] = []
        for definition in definitions:
            if definition.id in existing:
                msg = f"module compute node {definition.id!r} is already declared"
                raise ValueError(msg)
            existing.add(definition.id)
            operations.append(
                ModuleOperationDecl(
                    id=definition.id,
                    declaration_key=definition.declaration_key,
                    inputs=definition.inputs,
                    output_type=definition.output_type,
                )
            )
            implementations.append(
                ModulePythonImplementation(
                    declaration_key=definition.declaration_key,
                    fn=definition.fn,
                )
            )
        return replace(
            self,
            operations=(*self.operations, *operations),
            python_implementations=(
                *self.python_implementations,
                *implementations,
            ),
        )

    def measurement_transforms(
        self,
        *transforms: MeasurementTransform,
    ) -> ModuleBuilder:
        """Register pure product transforms independently of implementations."""

        existing = {
            transform.symbol_id for transform in self.measurement_transform_intents
        }
        if any(transform.symbol_id in existing for transform in transforms):
            raise ValueError("module measurement transform ids must be unique")
        supplied_ids = tuple(transform.symbol_id for transform in transforms)
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("module measurement transform ids must be unique")
        return replace(
            self,
            measurement_transform_intents=(
                *self.measurement_transform_intents,
                *transforms,
            ),
        )

    def product(
        self,
        *product_ids: str,
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
        producer_metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        """Declare products exposed by this reusable module.

        This only defines product identity, shape, and producer mapping. Use
        :meth:`acquire` to place hardware realization in the procedure; select
        durable records from a template or scratch experiment.
        """

        return replace(
            self,
            product_declarations=(
                *self.product_declarations,
                *(
                    ModuleProductDecl(
                        id=product_id,
                        origin=(object(),),
                        kind="observable",
                        resource_port_id=(
                            logical_resource_port_id(resource)
                            if resource is not None
                            else None
                        ),
                        capability=capability,
                        product_key=product_key,
                        unit=unit,
                        dtype=dtype,
                        axes=tuple(axes),
                        metadata=freeze_json_mapping(metadata or {}),
                        producer_metadata=freeze_json_mapping(producer_metadata or {}),
                    )
                    for product_id in product_ids
                ),
            ),
        )

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


@dataclass(frozen=True, slots=True, repr=False)
class ModuleInvocation:
    module: ExperimentModule
    instance_id: str
    inputs: Mapping[str, ValueRef] = field(default_factory=empty_frozen_mapping)
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId] = field(
        default_factory=_empty_resource_bindings
    )
    _key: InvocationKey = field(
        default_factory=InvocationKey.fresh,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)
        input_types = {
            port.id: port.value_type for port in self.module.ir.interface.imports
        }
        declared_inputs = set(input_types)
        unknown_inputs = sorted(set(self.inputs) - declared_inputs)
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.module.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)
        for input_id, value in self.inputs.items():
            require_assignable(
                value.value_type,
                input_types[input_id],
                path=("inputs", input_id),
            )
        missing_inputs = sorted(declared_inputs - set(self.inputs))
        if missing_inputs:
            missing = ", ".join(repr(input_id) for input_id in missing_inputs)
            msg = (
                f"module instance {self.instance_id!r} must connect all inputs: "
                f"{missing}"
            )
            raise ValueError(msg)
        declared_resources = {
            port.symbol_id for port in self.module.ir.interface.resources
        }
        unknown_resources = sorted(
            item.qualified_name
            for item in set(self.resource_bindings) - declared_resources
        )
        if unknown_resources:
            msg = "module instance binds undeclared resources: " + ", ".join(
                unknown_resources
            )
            raise ValueError(msg)

    @property
    def invocation_key(self) -> InvocationKey:
        """Typed nominal owner used by unresolved module-interface edges."""

        return self._key

    @property
    def outputs(self) -> ModuleOutputs:
        """Typed output values owned by this explicit module instance."""

        return ModuleOutputs(
            _values=FrozenMapping(
                (
                    port.id,
                    internal_module_export_value_ref(
                        self._key,
                        port.id,
                        port.value_type,
                    ),
                )
                for port in self.module.output_ports
            ),
        )

    @property
    def products(self) -> ProductOutputs:
        """Product references owned by this explicit module instance."""

        relative_ports = self.module.ir.interface.products
        relative_ids = tuple(port.qualified_id for port in relative_ports)
        duplicates = sorted(
            product_id
            for product_id in set(relative_ids)
            if relative_ids.count(product_id) > 1
        )
        if duplicates:
            duplicate_list = ", ".join(repr(product_id) for product_id in duplicates)
            msg = (
                f"module {self.module.id!r} has duplicate exposed products: "
                f"{duplicate_list}"
            )
            raise ValueError(msg)
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id.prefixed(self.instance_id),
                    origin=(self._key, *port.target_origin),
                )
                for port in relative_ports
            }
        )


@dataclass(frozen=True, slots=True, repr=False)
class ModuleOutputs(Mapping[str, ValueRef]):
    """Read-only attribute and mapping view of one invocation's exports."""

    _values: Mapping[str, ValueRef]

    @override
    def __getitem__(self, output_id: str) -> ValueRef:
        return self._values[output_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, output_id: str) -> ValueRef:
        try:
            return self._values[output_id]
        except KeyError:
            msg = f"module instance has no output {output_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self._values))


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentModule:
    _ir: ModuleIR = field(repr=False)

    @property
    def ir(self) -> ModuleIR:
        """Return the explicit immutable definition behind this handle."""

        return self._ir

    @property
    def id(self) -> str:
        return self._ir.id

    @property
    def input_ports(self) -> tuple[ModuleInputPort, ...]:
        return self._ir.interface.imports

    @property
    def output_ports(self) -> tuple[ModuleValueExport, ...]:
        return self._ir.interface.exports

    @property
    def resource_ports(self) -> tuple[ResourcePort, ...]:
        return self._ir.interface.resources

    @property
    def bindings(self) -> tuple[ExperimentBindingIntent, ...]:
        return self._ir.body.bindings

    @property
    def state_intents(self) -> tuple[ExperimentStateIntent, ...]:
        return self._ir.body.state

    @property
    def actions(self) -> tuple[ModuleActionDecl, ...]:
        return self._ir.body.actions

    @property
    def domain_executions(self) -> tuple[DomainExecution, ...]:
        return self._ir.body.domain_executions

    @property
    def procedure(self) -> tuple[ModuleEffectIR, ...]:
        return self._ir.body.procedure

    @property
    def operations(self) -> tuple[ModuleOperationDecl, ...]:
        return self._ir.body.operations

    @property
    def python_implementations(self) -> tuple[ModulePythonImplementation, ...]:
        """Return local implementations stored outside the semantic body."""

        return self._ir.python_implementations

    @property
    def product_declarations(self) -> tuple[ModuleProductDecl, ...]:
        """Local product declarations consumed by the flattening pass."""

        return self._ir.body.products

    @property
    def metadata(self) -> Mapping[str, MetadataValue]:
        return self._ir.metadata

    def instantiate(
        self,
        instance_id: str,
        mapped_inputs: Mapping[str, ModuleInput] | None = None,
        /,
        *,
        resource_bindings: Mapping[str, str] | None = None,
        **inputs: ModuleInput,
    ) -> ModuleInvocation:
        """Create a hygienic, explicitly named module instance."""

        selected_inputs = dict(mapped_inputs or {})
        selected_inputs.update(inputs)
        return self._invocation(
            instance_id,
            selected_inputs,
            resource_bindings=resource_bindings or {},
        )

    def domain(self, execution: DomainExecution) -> ExperimentModule:
        """Return this module with one domain call appended to its procedure."""

        if execution.id in {item.id for item in self.domain_executions}:
            raise ValueError(f"domain execution id {execution.id!r} is repeated")
        return ExperimentModule(
            _ir=replace(
                self._ir,
                body=replace(
                    self._ir.body,
                    procedure=(
                        *self._ir.body.procedure,
                        ModuleDomainEffect(execution),
                    ),
                ),
            )
        )

    def _invocation(
        self,
        instance_id: str,
        inputs: Mapping[str, ModuleInput],
        *,
        resource_bindings: Mapping[str, str],
    ) -> ModuleInvocation:
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
        input_types = {port.id: port.value_type for port in self._ir.interface.imports}
        unknown_inputs = sorted(set(inputs) - set(input_types))
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)
        captured_inputs = freeze_module_inputs(inputs)
        normalized = FrozenMapping(
            (
                input_id,
                _module_input_value_ref(
                    value,
                    input_id=input_id,
                    value_type=input_types[input_id],
                ),
            )
            for input_id, value in captured_inputs.items()
        )
        return ModuleInvocation(
            module=self,
            instance_id=instance_id,
            inputs=normalized,
            resource_bindings=FrozenMapping(
                (
                    logical_resource_port_id(child_id),
                    logical_resource_port_id(parent_id),
                )
                for child_id, parent_id in resource_bindings.items()
            ),
            _key=InvocationKey.fresh(),
        )

    @property
    def products(self) -> ProductOutputs:
        """Typed product references at this module's template boundary."""

        ports = self._ir.interface.products
        product_ids = tuple(port.qualified_id for port in ports)
        duplicates = sorted(
            product_id
            for product_id in set(product_ids)
            if product_ids.count(product_id) > 1
        )
        if duplicates:
            duplicate_list = ", ".join(repr(product_id) for product_id in duplicates)
            msg = f"module {self.id!r} has duplicate exposed products: {duplicate_list}"
            raise ValueError(msg)
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id,
                    origin=port.target_origin,
                )
                for port in ports
            }
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


def _module_input_value_ref(
    value: object,
    *,
    input_id: str,
    value_type: ValueType,
) -> ValueRef:
    path = ("inputs", input_id)
    if isinstance(value, ValueRef):
        require_assignable(value.value_type, value_type, path=path)
        return value
    return internal_literal_value_ref(value, value_type, path=path)


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
    if not _is_state_row_value(value):
        return value
    resolved: object = value(row)
    if not isinstance(resolved, ValueRef):
        msg = f"{path} callback must return a typed value"
        raise TypeError(msg)
    return resolved


def _is_state_row_value(
    value: object,
) -> TypeGuard[Callable[[TableRow], object]]:
    return callable(value)


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
        selected = value
        return cast(
            "tuple[ClosedScalarValue, ...]",
            tuple(_capture_state_literal(item) for item in selected),
        )
    return cast("ClosedScalarValue", _capture_state_literal(value))


def _capture_state_literal(value: object) -> object:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value
    return freeze_runtime_input(value)
