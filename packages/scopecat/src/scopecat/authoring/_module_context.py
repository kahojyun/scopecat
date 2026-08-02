"""Explicit module definition recorder and authoring-boundary normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast, overload

from scopecat.authoring._module_invocation import (
    DomainCallProvider,
    ModuleInvocation,
    domain_use_call,
    module_instance,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import freeze_json_mapping
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
from scopecat.kernel.value_types import Payload
from scopecat.measurements.results import MeasurementDType
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    ResourcePort,
    ResourceSelector,
    invoke_operation,
    resource_port,
)
from scopecat.program.bindings import bind_property as binding_property
from scopecat.program.domain import DomainCall
from scopecat.program.input_capture import capture_runtime_input
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.module import (
    ModuleAcquireEffect,
    ModuleAcquireResult,
    ModuleBody,
    ModuleDef,
    ModuleEffect,
    ModuleInstance,
    ModuleInterface,
    ModulePythonImplementation,
    ModuleValueExport,
)
from scopecat.program.operations import ModuleInputPort, ModuleOperationDecl
from scopecat.program.products import (
    ModuleProductDecl,
    ProductAxis,
    ProductOutputs,
    ProductRecording,
    ProductRef,
)
from scopecat.program.state import DesiredState, StateBinding
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_operation_id,
)
from scopecat.program.value_types import Entity as EntityType
from scopecat.program.value_types import Scalar as ScalarType
from scopecat.program.value_types import ValueType
from scopecat.program.values import (
    ComputeFunction,
    ComputeInput,
    MetadataValue,
)
from scopecat.program.values import compute as define_compute

type BindingInput = StateBinding
type InvocationInput = BindingInput | None


def _is_entity_input_type(value_type: ValueType) -> bool:
    return isinstance(value_type, ScalarType) and isinstance(
        value_type.atom, EntityType
    )


def _is_public_state_binding(value: object) -> bool:
    return (
        isinstance(value, ValueRef) and isinstance(value.value_type, ScalarType)
    ) or isinstance(value, Quantity | EntityRef | str | int | float | bool)


def _is_public_invocation_input(value: object) -> bool:
    return value is None or _is_public_state_binding(value)


def _require_public_state_binding(value: object) -> None:
    if value is None:
        raise TypeError(
            "persistent state bindings cannot be None; omit the property instead"
        )
    if _is_payload_binding_input(value):
        raise TypeError("persistent properties cannot contain opaque payloads")
    if not _is_public_state_binding(value):
        raise TypeError(
            "module bindings require a scalar typed value or scalar literal"
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

        self._effects.append(module_instance(invocation))

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
    ) -> tuple[ModuleInterface, ModuleBody, tuple[ModulePythonImplementation, ...]]:
        """Freeze the structural parts owned directly by an experiment."""

        return (
            ModuleInterface(
                imports=tuple(input_ports),
                resources=tuple(self._resources),
            ),
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

    def _resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> DefinitionResource:
        """Declare a generated client's logical resource."""

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

    def _bind_property(
        self,
        resource: DefinitionResource,
        property: PropertyRef,
        *,
        value: BindingInput,
    ) -> None:
        """Record a generated client's persistent property binding."""

        self._require_owned_resource(resource)
        _require_public_state_binding(value)
        self._effects.append(
            binding_property(
                resource.id,
                interface=property.interface_id,
                component_path=property.component_path,
                property=property.property_id,
                value=cast("BindingInput", _capture_binding_literal(value)),
            )
        )

    def _ensure(self, resource: DefinitionResource, target: DesiredState) -> None:
        """Record a generated client's coherent resource target state."""

        self._require_owned_resource(resource)
        self._effects.append(build_ensure_state_intent(resource.port_id, target))

    def _invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, InvocationInput] | None = None,
    ) -> None:
        """Record a generated client's ordered atomic hardware operation."""

        self._require_owned_resource(resource)
        selected_arguments = arguments or {}
        if any(target.operation != operation for target in selected_arguments):
            raise ValueError(
                "module invocation arguments must belong to the selected operation"
            )
        if any(
            not _is_public_invocation_input(value)
            for value in selected_arguments.values()
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
                        "InvocationInput", _capture_binding_literal(value)
                    )
                    for target, value in selected_arguments.items()
                },
            )
        )

    def product(
        self,
        id: str,
        *,
        scope: Sequence[str] = (),
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ProductRef:
        """Declare and return one module-owned logical product."""

        return self._product(
            id,
            scope=scope,
            unit=unit,
            dtype=dtype,
            axes=axes,
            metadata=metadata,
        )

    def _product(
        self,
        id: str,
        *,
        scope: Sequence[str] = (),
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        recording: ProductRecording | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ProductRef:
        """Declare a product carrying generated-client recording provenance."""

        declaration = ModuleProductDecl(
            id,
            scope=tuple(scope),
            origin=(object(),),
            unit=unit,
            dtype=dtype,
            axes=tuple(axes),
            recording=recording,
            metadata=freeze_json_mapping(metadata or {}),
        )
        self._product_declarations.append(declaration)
        return ProductRef(
            product_id=declaration.product_id,
            origin=declaration.origin,
            _recording=declaration.recording,
        )

    def _acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        """Map a generated client's acquisition results to declared products."""

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
                    _recording=(
                        None
                        if product.recording is None
                        else product.recording.prefixed(instance.instance_id)
                    ),
                )
                for instance in self._effects
                if isinstance(instance, ModuleInstance)
                for product in instance.module.products
            ),
            *(
                ProductRef(
                    product_id=product.product_id,
                    origin=product.origin,
                    _recording=product.recording,
                )
                for product in self._product_declarations
            ),
        )
        return ProductOutputs({product.id: product for product in products})

    def _require_owned_resource(self, resource: DefinitionResource) -> None:
        if resource.owner is not self._owner:
            raise ValueError("definition resource must belong to this module context")

    def require_owned_resource_internal(
        self,
        resource: DefinitionResource,
    ) -> None:
        """Validate a resource at a containing authoring boundary."""

        self._require_owned_resource(resource)

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
        _require_public_state_binding(value)
        bindings.append(
            binding_property(
                resource,
                interface=property.interface_id,
                component_path=property.component_path,
                property=property.property_id,
                value=cast("BindingInput", _capture_binding_literal(value)),
            )
        )
    return EnsureStateIntent(tuple(bindings))


def _capture_binding_literal(value: object) -> object:
    if isinstance(value, ValueRef):
        return value
    return capture_runtime_input(value)


def _is_payload_binding_input(value: object) -> bool:
    return isinstance(value, PayloadValue) or (
        isinstance(value, ValueRef)
        and isinstance(value.value_type, ScalarType)
        and isinstance(value.value_type.atom, Payload)
    )
