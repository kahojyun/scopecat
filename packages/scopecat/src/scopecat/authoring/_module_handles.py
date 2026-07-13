"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from scopecat._frozen import FrozenMapping, freeze_json_mapping
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
    ComputeNodeIntent,
    ExperimentStateIntent,
    ModuleInputPort,
    ModuleOutputPort,
    StateEachIntent,
    StateRouteValue,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    ProductOutputs,
    RecordAxis,
    RecordIntent,
    RecordSource,
    internal_product_outputs,
    internal_product_ref,
    observable,
    prefix_product_port,
    record_axis_intents,
)
from scopecat.authoring._value_refs import (
    TableRow,
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_literal_value_ref,
    internal_scope_compute_value_ref,
    internal_value_ref_input_id,
    internal_value_ref_source_kind,
    require_assignable,
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
    compute_origin_internal,
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
    output_ports: tuple[ModuleOutputPort, ...] = ()
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
                self.output_ports,
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
        ports: list[ModuleOutputPort] = []
        for output_id, value in values.items():
            raw_value = cast("object", value)
            if not output_id:
                msg = "module output ids must be non-empty"
                raise ValueError(msg)
            if output_id in existing:
                msg = f"module output {output_id!r} is already declared"
                raise ValueError(msg)
            if not isinstance(raw_value, ValueRef):
                msg = f"module output {output_id!r} must be a typed value"
                raise TypeError(msg)
            value = raw_value
            existing.add(output_id)
            ports.append(
                ModuleOutputPort(
                    id=output_id,
                    value=value,
                    value_type=value.value_type,
                )
            )
        return replace_handle(self, output_ports=(*self.output_ports, *ports))

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
        row = TableRow._from_value(  # pyright: ignore[reportPrivateUsage]
            relation
        )
        if not capability or not field:
            msg = "state capability and field ids must be non-empty"
            raise ValueError(msg)
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
                    origin=(compute_origin_internal(definition),),
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
                        origin=(object(),),
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
    instance_id: str | None = None
    inputs: Mapping[str, ModuleInput] = field(default_factory=empty_frozen_mapping)
    _origin: object = field(default_factory=object, repr=False, compare=False)

    def __init__(self) -> None:
        msg = (
            "ModuleInvocation is an opaque handle; create invocations by calling "
            "an ExperimentModule"
        )
        raise TypeError(msg)

    def __post_init__(self) -> None:
        if self.instance_id is not None and not self.instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)
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
        input_types = module_exposed_input_types_internal(self.module)
        declared_inputs = set(input_types)
        unknown_inputs = sorted(set(self.inputs) - declared_inputs)
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.module.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)
        for input_id, value in self.inputs.items():
            _module_input_value_ref(
                value,
                input_id=input_id,
                value_type=input_types[input_id],
            )
        if self.instance_id is not None:
            missing_inputs = sorted(declared_inputs - set(self.inputs))
            if missing_inputs:
                missing = ", ".join(repr(input_id) for input_id in missing_inputs)
                msg = (
                    f"module instance {self.instance_id!r} must connect all inputs: "
                    f"{missing}"
                )
                raise ValueError(msg)

    @property
    def outputs(self) -> ModuleOutputs:
        """Typed output values owned by this explicit module instance."""

        if self.instance_id is None:
            msg = (
                f"module {self.module.id!r} outputs require an explicit instance; "
                "use module.instantiate(instance_id, **inputs)"
            )
            raise ValueError(msg)
        input_refs = module_invocation_input_refs_internal(self)
        return create_handle(
            ModuleOutputs,
            _values=FrozenMapping(
                (
                    port.id,
                    internal_bind_value_ref_inputs(
                        internal_scope_compute_value_ref(
                            port.value,
                            self.instance_id,
                            origin=(self._origin,),
                        ),
                        input_refs,
                    ),
                )
                for port in self.module.output_ports
            ),
        )

    @property
    def products(self) -> ProductOutputs:
        """Product references owned by this explicit module instance."""

        if self.instance_id is None:
            msg = (
                f"module {self.module.id!r} products require an explicit instance; "
                "use module.instantiate(instance_id, **inputs)"
            )
            raise ValueError(msg)
        relative_ports = module_exposed_product_ports_internal(self.module)
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
                port.qualified_id: internal_product_ref(
                    prefix_product_port(
                        port,
                        self.instance_id,
                        origin=(self._origin,),
                    )
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

    def __getitem__(self, output_id: str) -> ValueRef:
        return self._values[output_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, output_id: str) -> ValueRef:
        try:
            return self._values[output_id]
        except KeyError:
            msg = f"module instance has no output {output_id!r}"
            raise AttributeError(msg) from None

    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self._values))


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ExperimentModule:
    id: str
    invocations: tuple[ModuleInvocation, ...] = ()
    input_ports: tuple[ModuleInputPort, ...] = ()
    output_ports: tuple[ModuleOutputPort, ...] = ()
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
        """Create a legacy index-scoped invocation.

        Legacy invocations remain composable through :meth:`ModuleBuilder.use`,
        but their outputs cannot be referenced before composition because they
        do not yet have a stable instance identity.
        """

        return self._invocation(None, inputs)

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
        instance_id: str | None,
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
        return create_handle(
            ModuleInvocation,
            module=self,
            instance_id=instance_id,
            inputs=cast("Mapping[str, ModuleInput]", freeze_module_inputs(inputs)),
            _origin=object(),
        )

    @property
    def products(self) -> ProductOutputs:
        """Typed product references at this module's template boundary."""

        ports = module_exposed_product_ports_internal(self)
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
            {port.qualified_id: internal_product_ref(port) for port in ports}
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


def _module_has_fixed_records(module: ExperimentModule) -> bool:
    return bool(module.records) or any(
        _module_has_fixed_records(invocation.module)
        for invocation in module.invocations
    )


def module_exposed_product_ports_internal(
    module: ExperimentModule,
) -> tuple[ModuleProductPort, ...]:
    """Collect product ports with explicit nested instance scopes attached."""

    result: list[ModuleProductPort] = []
    for invocation in module.invocations:
        nested = module_exposed_product_ports_internal(invocation.module)
        result.extend(
            prefix_product_port(
                product,
                *(
                    (invocation.instance_id,)
                    if invocation.instance_id is not None
                    else ()
                ),
                origin=(module_invocation_origin_internal(invocation),),
            )
            for product in nested
        )
    result.extend(module.product_ports)
    return tuple(result)


def module_invocation_input_refs_internal(
    invocation: ModuleInvocation,
) -> dict[str, ValueRef]:
    """Return supplied invocation inputs as validated typed value edges."""

    input_types = module_exposed_input_types_internal(invocation.module)
    return {
        input_id: _module_input_value_ref(
            value,
            input_id=input_id,
            value_type=input_types[input_id],
        )
        for input_id, value in invocation.inputs.items()
    }


def module_invocation_origin_internal(invocation: ModuleInvocation) -> object:
    """Return the nominal identity owned by one invocation handle."""

    return object.__getattribute__(invocation, "_origin")


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
    "ModuleOutputs",
]
