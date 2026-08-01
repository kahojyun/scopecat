"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast, overload, override

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.instrument_members import (
    AcquisitionResultRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.kernel.value_types import Payload
from scopecat.measurements.results import MeasurementDType
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
    ResourceSelector,
    invoke_operation,
    resource_port,
)
from scopecat.program.bindings import (
    bind_property as binding_property,
)
from scopecat.program.domain import DomainCall
from scopecat.program.identities import InvocationKey
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.module import (
    ModuleAcquireEffect,
    ModuleAcquireResult,
    ModuleBody,
    ModuleDef,
    ModuleEffect,
    ModuleImportBinding,
    ModuleInstance,
    ModuleInstanceLookup,
    ModuleInterface,
    ModulePythonImplementation,
    ModuleResourceBinding,
    ModuleValueExport,
)
from scopecat.program.operations import (
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.program.products import (
    ModuleProductDecl,
    ProductAxis,
    ProductOutputs,
    ProductRef,
)
from scopecat.program.state import DesiredState, StateBinding
from scopecat.program.value_refs import (
    ValueRef,
    capture_module_inputs,
    capture_runtime_input,
    empty_frozen_mapping,
    internal_literal_value_ref,
    internal_module_export_value_ref,
    internal_value_ref_operation_id,
)
from scopecat.program.value_types import (
    Entity as EntityType,
)
from scopecat.program.value_types import (
    Scalar as ScalarType,
)
from scopecat.program.value_types import ValueType
from scopecat.program.values import (
    ComputeFunction,
    ComputeInput,
    MetadataValue,
    ModuleInput,
)
from scopecat.program.values import (
    compute as define_compute,
)

type BindingInput = StateBinding
type InvocationInput = BindingInput


class DomainCallProvider(Protocol):
    """A domain frontend that exposes one native core call."""

    @property
    def domain_call(self) -> DomainCall: ...


def _empty_resource_bindings() -> FrozenMapping[
    LogicalResourcePortId, LogicalResourcePortId
]:
    return FrozenMapping()


def _is_entity_input_type(value_type: ValueType) -> bool:
    return isinstance(value_type, ScalarType) and isinstance(
        value_type.atom, EntityType
    )


def _is_public_binding_input(value: object) -> bool:
    return (
        (isinstance(value, ValueRef) and isinstance(value.value_type, ScalarType))
        or value is None
        or isinstance(
            value,
            Quantity | EntityRef | str | int | float | bool,
        )
    )


def _resource_interfaces(
    requires: Sequence[InterfaceRef],
) -> tuple[InterfaceId, ...]:
    return tuple(interface.interface_id for interface in requires)


@dataclass(frozen=True, slots=True)
class DefinitionResource:
    """One logical resource owned by a module definition context."""

    port_id: LogicalResourcePortId
    owner: object = field(repr=False, compare=False)

    @property
    def id(self) -> str:
        return self.port_id.local_id


class ModuleContext:
    """Explicit typed recorder injected into one ``@module`` definition."""

    __slots__ = (
        "_effects",
        "_measurement_postprocessors",
        "_operations",
        "_output_ports",
        "_owner",
        "_product_declarations",
        "_python_implementations",
        "_resources",
    )

    def __init__(self) -> None:
        self._owner = object()
        self._output_ports: list[ModuleValueExport] = []
        self._resources: list[ResourcePort] = []
        self._effects: list[ModuleEffect] = []
        self._operations: list[ModuleOperationDecl] = []
        self._python_implementations: list[ModulePythonImplementation] = []
        self._measurement_postprocessors: list[MeasurementPostprocessor] = []
        self._product_declarations: list[ModuleProductDecl] = []

    @property
    def effects_internal(self) -> tuple[ModuleEffect, ...]:
        """Return closed effects for the owning experiment context."""

        return tuple(self._effects)

    def append_invocation_internal(self, invocation: ModuleInvocation) -> None:
        """Append one child after immediately closing its interface bindings."""

        self._effects.append(_module_instance(invocation))

    def append_domain_call_internal(self, call: DomainCall) -> None:
        """Append one native domain occurrence and its result declarations."""

        self._effects.append(call.execution)
        self._product_declarations.extend(call.product_declarations)

    def close_definition_internal(
        self,
        *,
        id: str,
        input_ports: Sequence[ModuleInputPort] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleDef:
        """Freeze this context directly as one reusable module definition."""

        return ModuleDef(
            id=id,
            interface=ModuleInterface(
                imports=tuple(input_ports),
                exports=tuple(self._output_ports),
                resources=tuple(self._resources),
            ),
            body=self._close_body(),
            python_implementations=tuple(self._python_implementations),
            metadata=freeze_json_mapping(metadata or {}),
        )

    def close_experiment_parts_internal(
        self,
        *,
        input_ports: Sequence[ModuleInputPort] = (),
    ) -> tuple[
        ModuleInterface,
        ModuleBody,
        tuple[ModulePythonImplementation, ...],
    ]:
        """Freeze the structural parts owned directly by an experiment."""

        return (
            ModuleInterface(imports=tuple(input_ports)),
            self._close_body(),
            tuple(self._python_implementations),
        )

    def _close_body(self) -> ModuleBody:
        return ModuleBody(
            effects=tuple(self._effects),
            operations=tuple(self._operations),
            measurement_postprocessors=tuple(self._measurement_postprocessors),
            products=tuple(self._product_declarations),
        )

    @overload
    def call(self, part: ModuleInvocation) -> ModuleInvocation: ...

    @overload
    def call(self, part: DomainCall) -> DomainCall: ...

    @overload
    def call[T: DomainCallProvider](self, part: T) -> T: ...

    def call(
        self,
        part: ModuleInvocation | DomainCall | DomainCallProvider,
    ) -> ModuleInvocation | DomainCall | DomainCallProvider:
        """Append one explicitly constructed module or domain occurrence."""

        if isinstance(part, ModuleInvocation):
            self.append_invocation_internal(part)
            return part
        call = domain_use_call(part)
        self.append_domain_call_internal(call)
        return part

    def export(self, **values: ValueRef) -> None:
        """Expose typed values from each future invocation of this module."""

        for output_id, value in values.items():
            if not output_id:
                raise ValueError("module output ids must be non-empty")
            self._output_ports.append(ModuleValueExport(id=output_id, source=value))

    def resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> DefinitionResource:
        """Declare and return one logical resource owned by this module."""

        interfaces = _resource_interfaces(requires)
        for value in for_entities:
            if not _is_entity_input_type(value.value_type):
                raise TypeError("resource for_entities values must be entity-shaped")
            if internal_value_ref_operation_id(value) is not None:
                raise TypeError("resource for_entities cannot use compute outputs")
        self._resources.append(
            resource_port(
                id,
                ResourceSelector(
                    interfaces=interfaces,
                    entity_inputs=tuple(for_entities),
                ),
            )
        )
        return DefinitionResource(logical_resource_port_id(id), self._owner)

    def bind_property(
        self,
        resource: DefinitionResource,
        property: PropertyRef,
        *,
        value: BindingInput,
    ) -> None:
        """Bind one typed persistent property on a logical resource."""

        self._require_owned_resource(resource)
        if _is_payload_binding_input(value):
            raise TypeError("persistent properties cannot contain opaque payloads")
        if not _is_public_binding_input(value):
            raise TypeError(
                "module bindings require a scalar typed value or scalar literal"
            )
        self._effects.append(
            binding_property(
                resource.id,
                interface=property.interface_id,
                component_path=property.component_path,
                property=property.property_id,
                value=cast("BindingInput", _capture_binding_literal(value)),
            )
        )

    def ensure(
        self,
        resource: DefinitionResource,
        target: DesiredState,
    ) -> None:
        """Declare one coherent target state for a logical resource."""

        self._require_owned_resource(resource)
        self._effects.append(build_ensure_state_intent(resource.port_id, target))

    def invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, InvocationInput] | None = None,
    ) -> None:
        """Append one ordered atomic hardware operation."""

        self._require_owned_resource(resource)
        selected_arguments = arguments or {}
        if any(target.operation != operation for target in selected_arguments):
            raise ValueError(
                "module invocation arguments must belong to the selected operation"
            )
        if any(
            not _is_public_binding_input(value) for value in selected_arguments.values()
        ):
            raise TypeError("module invocation arguments require scalar values")
        self._effects.append(
            invoke_operation(
                id,
                port_id=resource.id,
                interface=operation.interface_id,
                component_path=operation.component_path,
                operation=operation.operation_id,
                arguments={
                    target.argument_id: cast(
                        "InvocationInput",
                        _capture_binding_literal(value),
                    )
                    for target, value in selected_arguments.items()
                },
            )
        )

    def product(
        self,
        id: str,
        *,
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ProductRef:
        """Declare and return one module-owned logical product."""

        declaration = ModuleProductDecl(
            id,
            origin=(object(),),
            unit=unit,
            dtype=dtype,
            axes=tuple(axes),
            metadata=freeze_json_mapping(metadata or {}),
        )
        self._product_declarations.append(declaration)
        return ProductRef(
            product_id=declaration.product_id,
            origin=declaration.origin,
        )

    def acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        """Map one acquisition's typed results to declared products."""

        self._require_owned_resource(resource)
        if not id or not results:
            raise ValueError("acquire requires a non-empty id and result mapping")
        available_products = self._products()
        selected_results: list[tuple[AcquisitionResultRef, ProductRef]] = []
        for result, product in results.items():
            expected_product = available_products.get(product.id)
            if (
                expected_product is None
                or expected_product.product_id != product.product_id
                or expected_product.origin != product.origin
            ):
                raise ValueError(
                    "acquire result references a product outside this module: "
                    f"{product.id!r}"
                )
            selected_results.append((result, expected_product))
        acquisition = selected_results[0][0].acquisition
        if any(result.acquisition != acquisition for result, _ in selected_results):
            raise ValueError("acquire results must belong to one acquisition")
        selected_products = tuple(product for _, product in selected_results)
        if len({product.product_id for product in selected_products}) != len(
            selected_products
        ):
            raise ValueError("acquire results must map to unique products")
        selected_metadata = freeze_json_mapping(metadata or {})
        self._effects.append(
            ModuleAcquireEffect(
                id=id,
                resource_port_id=resource.port_id,
                interface_id=acquisition.interface_id,
                component_path=acquisition.component_path,
                acquisition_id=acquisition.acquisition_id,
                results=tuple(
                    ModuleAcquireResult(
                        product=product,
                        result_id=result.result_id,
                        metadata=selected_metadata,
                    )
                    for result, product in selected_results
                ),
            )
        )

    def _products(self) -> ProductOutputs:
        products = (
            *(
                ProductRef(
                    product_id=product.symbol_id.prefixed(instance.instance_id),
                    origin=(instance.invocation_key, *product.target_origin),
                )
                for instance in self._effects
                if isinstance(instance, ModuleInstance)
                for product in instance.module.products
            ),
            *(
                ProductRef(
                    product_id=product.product_id,
                    origin=product.origin,
                )
                for product in self._product_declarations
            ),
        )
        return ProductOutputs({product.id: product for product in products})

    def _require_owned_resource(self, resource: DefinitionResource) -> None:
        if resource.owner is not self._owner:
            raise ValueError("definition resource must belong to this module context")

    def compute(
        self,
        id: str,
        *,
        fn: ComputeFunction,
        inputs: Mapping[str, ComputeInput] | None = None,
        output_type: ScalarType,
    ) -> ValueRef:
        """Declare one compute node and return its typed result."""

        definition = define_compute(
            id,
            fn=fn,
            inputs=inputs,
            output_type=output_type,
        )
        self._operations.append(
            ModuleOperationDecl(
                id=definition.id,
                declaration_key=definition.declaration_key,
                input_types=definition.input_types,
                inputs=definition.inputs,
                output_type=definition.output_type,
            )
        )
        self._python_implementations.append(
            ModulePythonImplementation(
                declaration_key=definition.declaration_key,
                fn=definition.fn,
            )
        )
        return definition.output

    def measurement_postprocessor(
        self,
        postprocessor: MeasurementPostprocessor,
    ) -> None:
        """Register one point-local measurement calculation."""

        self._measurement_postprocessors.append(postprocessor)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ModuleInvocation:
    module: ExperimentModule[...]
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

    def __init__(self) -> None:
        msg = "ModuleInvocation is created by calling or instantiating a module"
        raise TypeError(msg)

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

        relative_ports = self.module.definition.products
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id.prefixed(self.instance_id),
                    origin=(self._key, *port.target_origin),
                )
                for port in relative_ports
            }
        )

    @property
    def resources(self) -> ModuleResources:
        """Typed references to this instance's logical resource ports."""

        return ModuleResources(
            _values=FrozenMapping(
                (
                    port.qualified_id,
                    ModuleResource(
                        owner=self._key,
                        port_id=self.resource_bindings.get(
                            port.symbol_id,
                            port.symbol_id.prefixed(self.instance_id),
                        ),
                    ),
                )
                for port in self.module.resource_ports
            )
        )


@dataclass(frozen=True, slots=True)
class ModuleResource:
    """One logical resource as seen from a concrete module invocation."""

    owner: InvocationKey = field(repr=False)
    port_id: LogicalResourcePortId

    @property
    def id(self) -> str:
        return self.port_id.qualified_name


@dataclass(frozen=True, slots=True, repr=False)
class ModuleResources(Mapping[str, ModuleResource]):
    """Read-only attribute and mapping view of invocation resources."""

    _values: Mapping[str, ModuleResource]

    @override
    def __getitem__(self, resource_id: str) -> ModuleResource:
        return self._values[resource_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, resource_id: str) -> ModuleResource:
        try:
            return self._values[resource_id]
        except KeyError:
            msg = f"module instance has no resource {resource_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self._values))


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


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ExperimentModule[**P]:
    """One closed module definition with a single Python call contract."""

    _module_def: ModuleDef = field(repr=False)
    _authoring_fn: Callable[P, object] | None = field(
        repr=False,
        compare=False,
    )
    _signature: inspect.Signature = field(repr=False, compare=False)

    def __init__(self) -> None:
        msg = "ExperimentModule is created by @module"
        raise TypeError(msg)

    @property
    def definition(self) -> ModuleDef:
        """Return the explicit immutable definition behind this handle."""

        return self._module_def

    @property
    def id(self) -> str:
        return self._module_def.id

    @property
    def input_ports(self) -> tuple[ModuleInputPort, ...]:
        return self._module_def.interface.imports

    @property
    def output_ports(self) -> tuple[ModuleValueExport, ...]:
        return self._module_def.interface.exports

    @property
    def resource_ports(self) -> tuple[ResourcePort, ...]:
        return self._module_def.interface.resources

    @property
    def bindings(self) -> tuple[BindingIntent, ...]:
        return self._module_def.body.bindings

    @property
    def invocations(self) -> tuple[InvocationIntent, ...]:
        return self._module_def.body.invocations

    @property
    def effects(self) -> tuple[ModuleEffect, ...]:
        return self._module_def.body.effects

    @property
    def operations(self) -> tuple[ModuleOperationDecl, ...]:
        return self._module_def.body.operations

    @property
    def python_implementations(self) -> tuple[ModulePythonImplementation, ...]:
        """Return local implementations stored outside the semantic body."""

        return self._module_def.python_implementations

    @property
    def product_declarations(self) -> tuple[ModuleProductDecl, ...]:
        """Local product declarations consumed by the flattening pass."""

        return self._module_def.body.products

    @property
    def metadata(self) -> Mapping[str, MetadataValue]:
        return self._module_def.metadata

    @property
    def __wrapped__(self) -> Callable[P, object]:
        if self._authoring_fn is None:
            raise AttributeError("__wrapped__")
        return self._authoring_fn

    @property
    def __name__(self) -> str:
        return (
            self._authoring_fn.__name__
            if self._authoring_fn is not None
            else self.id.rsplit(".", maxsplit=1)[-1]
        )

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

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

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ModuleInvocation:
        """Create the ordinary single use of this closed definition."""

        bound = self._signature.bind(*args, **kwargs)
        inputs = dict(bound.arguments)
        variadic = next(
            (
                parameter.name
                for parameter in self._signature.parameters.values()
                if parameter.kind is inspect.Parameter.VAR_KEYWORD
            ),
            None,
        )
        if variadic is not None:
            inputs.update(
                cast(
                    "Mapping[str, ModuleInput]",
                    inputs.pop(variadic, {}),
                )
            )
        return self.instantiate(
            self.id.rsplit(".", maxsplit=1)[-1],
            cast("Mapping[str, ModuleInput]", inputs),
        )

    def _invocation(
        self,
        instance_id: str,
        inputs: Mapping[str, ModuleInput],
        *,
        resource_bindings: Mapping[str, str],
    ) -> ModuleInvocation:
        if not instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)
        try:
            captured_inputs = capture_module_inputs(
                cast("Mapping[str, object]", inputs)
            )
        except (TypeError, ValueError) as error:
            msg = (
                f"module {self.id!r} inputs require typed values or "
                f"closed literal data: {error}"
            )
            raise TypeError(msg) from error
        input_types = {
            port.id: port.value_type for port in self._module_def.interface.imports
        }
        unknown_inputs = sorted(set(inputs) - set(input_types))
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)
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
        missing_inputs = sorted(set(input_types) - set(normalized))
        if missing_inputs:
            missing = ", ".join(repr(input_id) for input_id in missing_inputs)
            msg = f"module instance {instance_id!r} must connect all inputs: {missing}"
            raise ValueError(msg)
        normalized_resource_bindings = FrozenMapping(
            (
                logical_resource_port_id(child_id),
                logical_resource_port_id(parent_id),
            )
            for child_id, parent_id in resource_bindings.items()
        )
        declared_resources = {
            port.symbol_id for port in self._module_def.interface.resources
        }
        unknown_resources = sorted(
            item.qualified_name
            for item in set(normalized_resource_bindings) - declared_resources
        )
        if unknown_resources:
            msg = "module instance binds undeclared resources: " + ", ".join(
                unknown_resources
            )
            raise ValueError(msg)
        return _create_module_invocation(
            module=self,
            instance_id=instance_id,
            inputs=normalized,
            resource_bindings=normalized_resource_bindings,
        )

    @property
    def products(self) -> ProductOutputs:
        """Typed product references at this module's template boundary."""

        ports = self._module_def.products
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id,
                    origin=port.target_origin,
                )
                for port in ports
            }
        )


@overload
def create_experiment_module_internal[**P](
    module_def: ModuleDef,
    *,
    definition: Callable[P, object],
    signature: inspect.Signature,
) -> ExperimentModule[P]: ...


@overload
def create_experiment_module_internal(
    module_def: ModuleDef,
    *,
    definition: None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]: ...


def create_experiment_module_internal(
    module_def: ModuleDef,
    *,
    definition: Callable[..., object] | None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]:
    """Close one module definition behind its authoring handle."""

    module = object.__new__(ExperimentModule)
    object.__setattr__(module, "_module_def", module_def)
    object.__setattr__(module, "_authoring_fn", definition)
    object.__setattr__(
        module,
        "_signature",
        signature.replace(return_annotation=ModuleInvocation),
    )
    return module


def _create_module_invocation(
    *,
    module: ExperimentModule[...],
    instance_id: str,
    inputs: Mapping[str, ValueRef],
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> ModuleInvocation:
    """Close values validated and normalized by ExperimentModule._invocation."""

    invocation = object.__new__(ModuleInvocation)
    object.__setattr__(invocation, "module", module)
    object.__setattr__(invocation, "instance_id", instance_id)
    object.__setattr__(invocation, "inputs", inputs)
    object.__setattr__(invocation, "resource_bindings", resource_bindings)
    object.__setattr__(invocation, "_key", InvocationKey.fresh())
    return invocation


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


def _capture_binding_literal(value: object) -> object:
    if isinstance(value, ValueRef):
        return value
    return capture_runtime_input(value)


def build_ensure_state_intent(
    resource: LogicalResourcePortId,
    target: DesiredState,
) -> EnsureStateIntent:
    """Normalize one public desired-state target at an authoring boundary."""

    assignments = tuple(target.target_assignments().items())
    if not assignments:
        raise ValueError("ensure requires at least one target assignment")

    bindings: list[BindingIntent] = []
    for property, value in assignments:
        if _is_payload_binding_input(value):
            raise TypeError("persistent properties cannot contain opaque payloads")
        if not _is_public_binding_input(value):
            msg = "module bindings require a scalar typed value or scalar literal"
            raise TypeError(msg)
        bindings.append(
            binding_property(
                resource,
                interface=property.interface_id,
                component_path=property.component_path,
                property=property.property_id,
                value=cast(
                    "BindingInput",
                    _capture_binding_literal(value),
                ),
            )
        )
    return EnsureStateIntent(tuple(bindings))


def _is_payload_binding_input(value: object) -> bool:
    return isinstance(value, PayloadValue) or (
        isinstance(value, ValueRef)
        and isinstance(value.value_type, ScalarType)
        and isinstance(value.value_type.atom, Payload)
    )


def _module_instance(invocation: ModuleInvocation) -> ModuleInstance:
    bindings = tuple(
        ModuleImportBinding(import_id=import_id, source=source)
        for import_id, source in invocation.inputs.items()
    )
    return ModuleInstance(
        lookup=ModuleInstanceLookup(
            invocation_key=invocation.invocation_key,
            instance_id=invocation.instance_id,
        ),
        module=invocation.module.definition,
        input_bindings=bindings,
        resource_bindings=tuple(
            ModuleResourceBinding(import_id=child_id, source_id=parent_id)
            for child_id, parent_id in invocation.resource_bindings.items()
        ),
    )


def module_use_invocation(
    selected: ModuleInvocation | object,
) -> ModuleInvocation:
    if isinstance(selected, ModuleInvocation):
        return selected
    msg = "module composition requires a ModuleInvocation"
    raise TypeError(msg)


def domain_use_call(
    selected: DomainCall | DomainCallProvider | object,
) -> DomainCall:
    if isinstance(selected, DomainCall):
        return selected
    call = getattr(selected, "domain_call", None)
    if isinstance(call, DomainCall):
        return call
    raise TypeError("domain composition requires a DomainCall")
