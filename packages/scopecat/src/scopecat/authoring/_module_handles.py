"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, override

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
from scopecat.authoring._handles import create_handle, replace_handle
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
    ModuleIR,
    ModulePythonImplementation,
    ModuleValueExport,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    ProductOutputs,
    RecordAxis,
    RecordIntent,
    internal_product_outputs,
    internal_product_ref_from_identity,
    observable,
    record_axis_intents,
)
from scopecat.authoring._value_refs import (
    TableRow,
    ValueDeclarationKey,
    ValueRef,
    internal_literal_value_ref,
    internal_module_export_value_ref,
    internal_value_ref_input_id,
    internal_value_ref_source_kind,
)
from scopecat.authoring.domain import DomainCall, DomainProgramDef
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
    compute_declaration_key_internal,
    module_input_is_valid,
)
from scopecat.compiler.relations.model import RowScopeId
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import logical_resource_port_id
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
    output_ports: tuple[ModuleValueExport, ...] = ()
    resources: tuple[ResourcePort, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    actions: tuple[ModuleActionDecl, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    measurement_transform_intents: tuple[MeasurementTransform, ...] = ()
    domain_programs: tuple[DomainProgramDef, ...] = ()
    domain_call_intents: tuple[DomainCall, ...] = ()
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
                self.output_ports,
                self.bindings,
                self.state_intents,
                self.actions,
                self.operations,
                self.python_implementations,
                self.measurement_transform_intents,
                self.domain_programs,
                self.domain_call_intents,
                self.records,
                self.product_ports,
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
        return replace_handle(self, invocations=combined)

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
        return replace_handle(self, output_ports=(*self.output_ports, *ports))

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
        return replace_handle(
            self,
            bindings=(
                *self.bindings,
                binding_field(
                    resource,
                    capability=capability,
                    field=field,
                    value=cast("BindingInput", _capture_state_literal(value)),
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
        row = TableRow._from_value(  # pyright: ignore[reportPrivateUsage]
            relation,
            scope_id=row_scope_id,
        )
        if not capability or not field:
            msg = "state capability and field ids must be non-empty"
            raise ValueError(msg)
        return replace_handle(
            self,
            state_intents=(
                *self.state_intents,
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
        return replace_handle(
            self,
            actions=(
                *self.actions,
                ModuleActionDecl(
                    id=id,
                    resource_port_id=logical_resource_port_id(resource),
                    capability_id=capability,
                    fields=tuple(
                        (name, cast("BindingInput", _capture_state_literal(value)))
                        for name, value in selected_fields.items()
                    ),
                ),
            ),
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
            declaration_key = compute_declaration_key_internal(definition)
            operations.append(
                ModuleOperationDecl(
                    id=definition.id,
                    declaration_key=declaration_key,
                    inputs=definition.inputs,
                    output_type=definition.output_type,
                )
            )
            implementations.append(
                ModulePythonImplementation(
                    declaration_key=declaration_key,
                    fn=definition.fn,
                )
            )
        return replace_handle(
            self,
            operations=(*self.operations, *operations),
            python_implementations=(
                *self.python_implementations,
                *implementations,
            ),
        )

    def domain_calls(self, *calls: DomainCall) -> ModuleBuilder:
        """Register independent compile-stage domain program invocations."""

        existing_calls = {call.symbol_id for call in self.domain_call_intents}
        if any(call.symbol_id in existing_calls for call in calls):
            raise ValueError("module domain call ids must be unique")
        programs = list(self.domain_programs)
        by_id = {program.symbol_id: program for program in programs}
        for call in calls:
            existing = by_id.get(call.program.symbol_id)
            if existing is not None and existing is not call.program:
                raise ValueError(
                    "one module cannot declare different domain programs with "
                    f"identity {call.program.symbol_id.qualified_name!r}"
                )
            if existing is None:
                programs.append(call.program)
                by_id[call.program.symbol_id] = call.program
        return replace_handle(
            self,
            domain_programs=tuple(programs),
            domain_call_intents=(*self.domain_call_intents, *calls),
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
        return replace_handle(
            self,
            measurement_transform_intents=(
                *self.measurement_transform_intents,
                *transforms,
            ),
        )

    def record(
        self,
        *record_ids: str,
        resource: str | None = None,
        capability: str | None = None,
        product_key: str | None = None,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[RecordAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
        producer_metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        return replace_handle(
            self,
            records=(
                *self.records,
                *(
                    observable(
                        record_id,
                        resource=resource,
                        capability=capability,
                        product_key=product_key,
                        unit=unit,
                        dtype=dtype,
                        axes=record_axis_intents(axes),
                        metadata=metadata,
                        producer_metadata=producer_metadata,
                    )
                    for record_id in record_ids
                ),
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
        axes: Sequence[RecordAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
        producer_metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        return replace_handle(
            self,
            product_ports=(
                *self.product_ports,
                *(
                    ModuleProductPort(
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
                        axes=record_axis_intents(axes),
                        metadata=freeze_json_mapping(metadata or {}),
                        producer_metadata=freeze_json_mapping(producer_metadata or {}),
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
    instance_id: str
    inputs: Mapping[str, ValueRef] = field(default_factory=empty_frozen_mapping)
    _key: InvocationKey = field(
        default_factory=InvocationKey.fresh,
        repr=False,
        compare=False,
    )

    def __init__(self) -> None:
        msg = (
            "ModuleInvocation is an opaque handle; create it with "
            "module.instantiate(instance_id, **inputs)"
        )
        raise TypeError(msg)

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

    @property
    def invocation_key(self) -> InvocationKey:
        """Typed nominal owner used by unresolved module-interface edges."""

        return self._key

    @property
    def outputs(self) -> ModuleOutputs:
        """Typed output values owned by this explicit module instance."""

        return create_handle(
            ModuleOutputs,
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
        return internal_product_outputs(
            {
                port.qualified_id: internal_product_ref_from_identity(
                    port.symbol_id.prefixed(self.instance_id),
                    origin=(self._key, *port.target_origin),
                )
                for port in relative_ports
            }
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ModuleOutputs(Mapping[str, ValueRef]):
    """Read-only attribute and mapping view of one invocation's exports."""

    _values: Mapping[str, ValueRef]

    def __init__(self) -> None:
        msg = (
            "ModuleOutputs is an opaque handle; obtain it from ModuleInvocation.outputs"
        )
        raise TypeError(msg)

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


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ExperimentModule:
    _ir: ModuleIR = field(repr=False)

    def __init__(self) -> None:
        msg = "ExperimentModule is an opaque handle; create it with module(...).build()"
        raise TypeError(msg)

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
    def operations(self) -> tuple[ModuleOperationDecl, ...]:
        return self._ir.body.operations

    @property
    def python_implementations(self) -> tuple[ModulePythonImplementation, ...]:
        """Return local implementations stored outside the semantic body."""

        return self._ir.python_implementations

    @property
    def records(self) -> tuple[RecordIntent, ...]:
        return self._ir.body.records

    @property
    def product_ports(self) -> tuple[ModuleProductPort, ...]:
        """Local product declarations consumed by the flattening pass."""

        return self._ir.body.products

    @property
    def metadata(self) -> Mapping[str, MetadataValue]:
        return self._ir.metadata

    def instantiate(
        self,
        instance_id: str,
        **inputs: ModuleInput,
    ) -> ModuleInvocation:
        """Create a hygienic, explicitly named module instance."""

        if _module_has_fixed_records(self):
            msg = (
                f"module {self.id!r} contains fixed records and cannot be "
                "instantiated; reusable modules must declare products and let "
                "the template select them"
            )
            raise ValueError(msg)
        return self._invocation(instance_id, inputs)

    def _invocation(
        self,
        instance_id: str,
        inputs: Mapping[str, ModuleInput],
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
        return create_handle(
            ModuleInvocation,
            module=self,
            instance_id=instance_id,
            inputs=normalized,
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
        return internal_product_outputs(
            {
                port.qualified_id: internal_product_ref_from_identity(
                    port.symbol_id,
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


def _module_has_fixed_records(module: ExperimentModule) -> bool:
    return _module_ir_has_fixed_records(module.ir)


def _module_ir_has_fixed_records(module: ModuleIR) -> bool:
    return bool(module.body.records) or any(
        _module_ir_has_fixed_records(instance.module)
        for instance in module.body.instances
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
        return value.model_copy()
    return freeze_runtime_input(value)


__all__ = [
    "ExperimentModule",
    "ModuleBuilder",
    "ModuleInvocation",
    "ModuleOutputs",
]
