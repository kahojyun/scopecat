"""Opaque module authoring handles and source-only normalization."""

from __future__ import annotations

import inspect
import keyword
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol, cast, overload, override

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    resource_port,
)
from scopecat.authoring._binding_intents import (
    bind_field as binding_field,
)
from scopecat.authoring._identities import InvocationKey
from scopecat.authoring._intents import (
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.authoring._module_ir import (
    ModuleAcquireEffect,
    ModuleAcquireProduct,
    ModuleBindingEffect,
    ModuleBodyIR,
    ModuleDomainEffect,
    ModuleEffectIR,
    ModuleImportBinding,
    ModuleInstanceIR,
    ModuleInstanceLookup,
    ModuleInterfaceIR,
    ModuleIR,
    ModulePythonImplementation,
    ModuleResourceBinding,
    ModuleValueExport,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
    ProductAxis,
    ProductOutputs,
    ProductRef,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    capture_module_inputs,
    capture_runtime_input,
    empty_frozen_mapping,
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
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import (
    Compute,
    MetadataValue,
    ModuleInput,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.measurements.results import MeasurementDType

type StateLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type BindingInput = StateLiteral | ValueRef


class ModuleCall(Protocol):
    """A domain frontend that exposes one core module invocation."""

    @property
    def module_invocation(self) -> ModuleInvocation: ...


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
    input_ports: tuple[ModuleInputPort, ...] = ()
    output_ports: tuple[ModuleValueExport, ...] = ()
    resources: tuple[ResourcePort, ...] = ()
    procedure: tuple[ModuleInvocation | ModuleEffectIR, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    measurement_transform_intents: tuple[MeasurementTransform, ...] = ()
    product_declarations: tuple[ModuleProductDecl, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    @property
    def products(self) -> ProductOutputs:
        """Stable references to products declared on this builder so far."""

        products = (
            *(
                product
                for invocation in self.procedure
                if isinstance(invocation, ModuleInvocation)
                for product in invocation.products.values()
            ),
            *(
                ProductRef(
                    product_id=product.product_id,
                    origin=product.origin,
                )
                for product in self.product_declarations
            ),
        )
        return ProductOutputs({product.id: product for product in products})

    def use(
        self,
        *modules: ModuleInvocation | ModuleCall,
    ) -> ModuleBuilder:
        invocations = tuple(module_use_invocation(module) for module in modules)
        return replace(
            self,
            procedure=(*self.procedure, *invocations),
        )

    def sequence(self, *modules: ModuleInvocation | ModuleCall) -> ModuleBuilder:
        """Append child procedures in deterministic sequence."""

        return self.use(*modules)

    @property
    def bindings(self) -> tuple[ExperimentBindingIntent, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleBindingEffect)
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

        ports: list[ModuleInputPort] = []
        for value in values:
            input_id = internal_value_ref_input_id(value)
            if input_id is None:
                msg = "module inputs must be input value references"
                raise TypeError(msg)
            ports.append(ModuleInputPort(id=input_id, value_type=value.value_type))
        return replace(self, input_ports=(*self.input_ports, *ports))

    def export(self, **values: ValueRef) -> ModuleBuilder:
        """Export named typed values from each future module instance.

        Exports are value edges for composition, not persisted measurement
        products.  Instantiate the built module to obtain instance-owned
        references through ``invocation.outputs``.
        """

        ports: list[ModuleValueExport] = []
        for output_id, value in values.items():
            if not output_id:
                msg = "module output ids must be non-empty"
                raise ValueError(msg)
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

    def domain(self, execution: DomainExecution) -> ModuleBuilder:
        """Append one opaque domain-program effect to this module procedure."""

        return replace(
            self,
            procedure=(*self.procedure, ModuleDomainEffect(execution)),
        )

    def acquire(
        self,
        id: str,  # noqa: A002
        *products: str | ProductRef,
        resource: str,
        capability: str,
        product_key: str | None = None,
        product_keys: Mapping[str | ProductRef, str] | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        """Acquire instrument products through one logical resource capability.

        ``product_key`` is the single-product shorthand. ``product_keys`` may
        override provider keys for any subset of a multi-product acquisition;
        products without an override keep their local logical id.
        """

        if not id or not products:
            raise ValueError("acquire requires a non-empty id and products")
        if not capability:
            raise ValueError("acquire requires a non-empty capability")
        if product_key is not None and product_keys is not None:
            raise ValueError("acquire accepts either product_key or product_keys")
        if product_key is not None and len(products) != 1:
            raise ValueError("acquire product_key is only valid for one product")
        if product_key is not None and not product_key:
            raise ValueError("acquire product_key must be non-empty")
        selected = tuple(
            self.products[product] if isinstance(product, str) else product
            for product in products
        )
        selected_by_id = {product.id: product for product in selected}
        provider_keys_by_product_id: dict[ProductId, str] = {}
        for key, provider_key in (product_keys or {}).items():
            if not provider_key:
                raise ValueError("acquire product_keys values must be non-empty")
            selected_id = key.id if isinstance(key, ProductRef) else key
            selected_product = selected_by_id.get(selected_id)
            if selected_product is None:
                raise ValueError(
                    "acquire product_keys references unselected product "
                    f"{selected_id!r}"
                )
            if selected_product.product_id in provider_keys_by_product_id:
                raise ValueError(
                    "acquire product_keys maps one selected product more than once: "
                    f"{selected_id!r}"
                )
            provider_keys_by_product_id[selected_product.product_id] = provider_key
        selected_metadata = freeze_json_mapping(metadata or {})
        return replace(
            self,
            procedure=(
                *self.procedure,
                ModuleAcquireEffect(
                    id=id,
                    resource_port_id=logical_resource_port_id(resource),
                    capability_id=capability,
                    products=tuple(
                        ModuleAcquireProduct(
                            product=product,
                            provider_key=(
                                product_key
                                if product_key is not None
                                else provider_keys_by_product_id.get(
                                    product.product_id,
                                    product.local_id,
                                )
                            ),
                            metadata=selected_metadata,
                        )
                        for product in selected
                    ),
                ),
            ),
        )

    def computes(self, *definitions: Compute) -> ModuleBuilder:
        """Register typed compute declarations and their output values."""

        operations: list[ModuleOperationDecl] = []
        implementations: list[ModulePythonImplementation] = []
        for definition in definitions:
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
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ModuleBuilder:
        """Declare products exposed by this reusable module.

        This only defines product identity and shape. Use :meth:`acquire` to
        place hardware realization in the procedure; select
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
                        unit=unit,
                        dtype=dtype,
                        axes=tuple(axes),
                        metadata=freeze_json_mapping(metadata or {}),
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
    ) -> ExperimentModule[...]:
        return build_module_from_builder(
            self,
            id=id,
            metadata=metadata,
        )


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

        relative_ports = self.module.ir.products
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


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ExperimentModule[**P]:
    """One closed module definition with a single Python call contract."""

    _ir: ModuleIR = field(repr=False)
    _definition: Callable[P, object] | None = field(
        repr=False,
        compare=False,
    )
    _signature: inspect.Signature = field(repr=False, compare=False)

    def __init__(self) -> None:
        msg = "ExperimentModule is created by @module or ModuleBuilder.build()"
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

    @property
    def __wrapped__(self) -> Callable[P, object]:
        if self._definition is None:
            raise AttributeError("__wrapped__")
        return self._definition

    @property
    def __name__(self) -> str:
        return (
            self._definition.__name__
            if self._definition is not None
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
        input_types = {port.id: port.value_type for port in self._ir.interface.imports}
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
        declared_resources = {port.symbol_id for port in self._ir.interface.resources}
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

        ports = self._ir.products
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
    ir: ModuleIR,
    *,
    definition: Callable[P, object],
    signature: inspect.Signature,
) -> ExperimentModule[P]: ...


@overload
def create_experiment_module_internal(
    ir: ModuleIR,
    *,
    definition: None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]: ...


def create_experiment_module_internal(
    ir: ModuleIR,
    *,
    definition: Callable[..., object] | None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]:
    """Close one module IR behind the internal decorator/builder boundary."""

    module = object.__new__(ExperimentModule)
    object.__setattr__(module, "_ir", ir)
    object.__setattr__(module, "_definition", definition)
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


def _capture_state_literal(value: object) -> object:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value
    return capture_runtime_input(value)


def build_module_ir(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleIR:
    """Close a builder at the single module-definition boundary."""

    module_id = id or builder.id
    if not module_id:
        msg = "module builder requires an id before conversion to ModuleIR"
        raise ValueError(msg)
    merged_metadata: dict[str, MetadataValue] = dict(builder.metadata)
    merged_metadata.update(dict(metadata or {}))
    closed_procedure = tuple(
        _module_instance_ir(effect) if isinstance(effect, ModuleInvocation) else effect
        for effect in builder.procedure
    )
    return ModuleIR(
        id=module_id,
        interface=ModuleInterfaceIR(
            imports=builder.input_ports,
            exports=builder.output_ports,
            resources=builder.resources,
        ),
        body=ModuleBodyIR(
            procedure=closed_procedure,
            operations=builder.operations,
            measurement_transforms=builder.measurement_transform_intents,
            products=builder.product_declarations,
        ),
        python_implementations=builder.python_implementations,
        metadata=freeze_json_mapping(merged_metadata),
    )


def _module_instance_ir(invocation: ModuleInvocation) -> ModuleInstanceIR:
    bindings = tuple(
        ModuleImportBinding(import_id=import_id, source=source)
        for import_id, source in invocation.inputs.items()
    )
    return ModuleInstanceIR(
        lookup=ModuleInstanceLookup(
            invocation_key=invocation.invocation_key,
            instance_id=invocation.instance_id,
        ),
        module=invocation.module.ir,
        input_bindings=bindings,
        resource_bindings=tuple(
            ModuleResourceBinding(import_id=child_id, source_id=parent_id)
            for child_id, parent_id in invocation.resource_bindings.items()
        ),
    )


def build_module_from_builder(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule[...]:
    module_ir = build_module_ir(builder, id=id, metadata=metadata)
    return create_experiment_module_internal(
        module_ir,
        signature=_module_signature(module_ir.interface.imports),
    )


def _module_signature(
    input_ports: Sequence[ModuleInputPort],
) -> inspect.Signature:
    input_ids = {port.id for port in input_ports}
    extra_name = "_inputs"
    while extra_name in input_ids:
        extra_name = f"_{extra_name}"
    parameters = [
        inspect.Parameter(
            port.id,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=port.value_type,
        )
        for port in input_ports
        if port.id.isidentifier() and not keyword.iskeyword(port.id)
    ]
    parameters.append(
        inspect.Parameter(
            extra_name,
            inspect.Parameter.VAR_KEYWORD,
        )
    )
    return inspect.Signature(parameters)


def module_use_invocation(
    selected: ModuleInvocation | ModuleCall | object,
) -> ModuleInvocation:
    if isinstance(selected, ModuleInvocation):
        return selected
    invocation = getattr(selected, "module_invocation", None)
    if isinstance(invocation, ModuleInvocation):
        return invocation
    msg = "module composition requires a ModuleInvocation or a domain module call"
    raise TypeError(msg)
