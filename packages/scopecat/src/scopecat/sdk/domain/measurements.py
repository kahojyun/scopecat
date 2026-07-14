"""Host implementation selection for authored domain measurement transforms.

Core projects authored product edges into a :class:`DomainBatchContext`.
Laboratory adapters may inspect those immutable capabilities and bind host
implementations, but they cannot create or rewire transform declarations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.contracts import validated_measurement_value_copy
from scopecat.measurements.host_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformImplementation,
)
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    MeasurementTransformInputPort,
    MeasurementTransformOutputPort,
    NativeMeasurementTransformId,
)
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.domain.context import (
    DomainBatchContext,
    context_linked_points_internal,
    point_id_internal,
    product_use_id_internal,
)
from scopecat.sdk.domain.view import (
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductContractView,
    DomainProductUseRef,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)

type DomainTransformRate = Literal["point"]
type DomainHostTransformValidator = Callable[["DomainMeasurementTransform"], None]
type DomainHostTransformKernel = Callable[
    ["DomainHostTransformCall"],
    Mapping[str, MeasurementValue],
]


@dataclass(frozen=True, slots=True)
class DomainHostTransformCall:
    """One point-local SDK call delivered to a laboratory host kernel."""

    transform: DomainMeasurementTransform
    point: DomainPointRef
    inputs: Mapping[str, MeasurementValue] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(
            cast("object", self.transform),
            DomainMeasurementTransform,
        ):
            msg = "domain host transform calls require a transform declaration"
            raise TypeError(msg)
        if not isinstance(cast("object", self.point), DomainPointRef):
            msg = "domain host transform calls require a DomainPointRef"
            raise TypeError(msg)
        raw_inputs = cast("Mapping[object, object]", cast("object", self.inputs))
        try:
            candidates = dict(raw_inputs)
        except Exception as error:
            msg = "domain host transform call inputs must be a readable mapping"
            raise TypeError(msg) from error
        expected = {port.id for port in self.transform.inputs}
        if set(candidates) != expected:
            msg = "domain host transform call inputs must exactly match input roles"
            raise ValueError(msg)
        if any(not isinstance(port_id, str) for port_id in candidates):
            msg = "domain host transform call input ids must be strings"
            raise TypeError(msg)
        try:
            selected = {
                cast("str", port_id): validated_measurement_value_copy(
                    cast("MeasurementValue", value)
                )
                for port_id, value in candidates.items()
            }
        except (AttributeError, TypeError, ValueError) as error:
            msg = "domain host transform call inputs must be measurement values"
            raise TypeError(msg) from error
        object.__setattr__(self, "inputs", MappingProxyType(selected))

    @property
    def transform_id(self) -> str:
        return self.transform.id

    @property
    def semantic(self) -> MeasurementTransformSemanticContract:
        return self.transform.semantic.model_copy(deep=True)

    @property
    def input_ports(self) -> tuple[DomainTransformInputPort, ...]:
        return self.transform.inputs

    @property
    def output_ports(self) -> tuple[DomainTransformOutputPort, ...]:
        return self.transform.outputs

    @property
    def point_index(self) -> int:
        return self.point.ordinal


@dataclass(frozen=True, slots=True)
class DomainHostTransformImplementation:
    """Transient SDK host callable for one semantic transform family."""

    id: str
    semantic_id: str
    semantic_version: str
    implementation_fingerprint: str
    validate_transform: DomainHostTransformValidator = field(
        repr=False,
        compare=False,
    )
    kernel: DomainHostTransformKernel = field(repr=False, compare=False)
    rate: DomainTransformRate = "point"

    def __post_init__(self) -> None:
        text_fields = (
            self.id,
            self.semantic_id,
            self.semantic_version,
            self.implementation_fingerprint,
        )
        if any(not isinstance(cast("object", value), str) for value in text_fields):
            msg = "domain host transform implementation fields must be strings"
            raise TypeError(msg)
        if not all(text_fields):
            msg = "domain host transform implementation fields must be non-empty"
            raise ValueError(msg)
        if self.rate != "point":
            msg = "domain host transform implementations support point rate only"
            raise ValueError(msg)
        if not callable(self.validate_transform):
            msg = "domain host transform validator must be callable"
            raise TypeError(msg)
        if not callable(self.kernel):
            msg = "domain host transform kernel must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class DomainHostTransformBinding:
    """Explicit host implementation selection for one SDK transform."""

    transform: DomainMeasurementTransform
    implementation: DomainHostTransformImplementation

    def __post_init__(self) -> None:
        if not isinstance(
            cast("object", self.transform),
            DomainMeasurementTransform,
        ):
            msg = "domain host transform bindings require a transform declaration"
            raise TypeError(msg)
        if not isinstance(
            cast("object", self.implementation),
            DomainHostTransformImplementation,
        ):
            msg = "domain host transform bindings require a host implementation"
            raise TypeError(msg)
        semantic = self.transform.semantic
        implementation = self.implementation
        if (
            implementation.semantic_id != semantic.id
            or implementation.semantic_version != semantic.version
            or implementation.rate != self.transform.rate
        ):
            msg = "domain host transform implementation is semantically incompatible"
            raise ValueError(msg)


def lower_domain_measurement_transform_internal(
    context: DomainBatchContext,
    transform: DomainMeasurementTransform,
) -> MeasurementTransformDef:
    """Lower one context-owned SDK declaration into the existing core graph."""

    _require_context(context)
    if not isinstance(cast("object", transform), DomainMeasurementTransform):
        msg = "domain transform lowering requires DomainMeasurementTransform"
        raise TypeError(msg)
    return MeasurementTransformDef(
        id=NativeMeasurementTransformId(transform.id),
        semantic=transform.semantic.model_copy(deep=True),
        rate=transform.rate,
        inputs=tuple(
            _lower_input_port(context, port)
            for port in sorted(transform.inputs, key=lambda item: item.id)
        ),
        outputs=tuple(
            _lower_output_port(context, port)
            for port in sorted(transform.outputs, key=lambda item: item.id)
        ),
    )


def lower_domain_host_transform_implementation_internal(
    context: DomainBatchContext,
    transform: DomainMeasurementTransform,
    implementation: DomainHostTransformImplementation,
) -> HostMeasurementTransformImplementation:
    """Adapt one SDK validator/kernel pair to the existing host executor."""

    _require_context(context)
    if not isinstance(cast("object", transform), DomainMeasurementTransform):
        msg = "domain host implementation lowering requires a transform"
        raise TypeError(msg)
    if not isinstance(
        cast("object", implementation),
        DomainHostTransformImplementation,
    ):
        msg = "domain host implementation lowering requires an implementation"
        raise TypeError(msg)
    DomainHostTransformBinding(transform, implementation)
    native_transform = lower_domain_measurement_transform_internal(context, transform)
    point_refs = {point_id_internal(point): point for point in context.points}

    def validate(candidate: MeasurementTransformDef) -> None:
        if candidate != native_transform:
            msg = "lowered host implementation received another transform contract"
            raise ValueError(msg)
        implementation.validate_transform(transform)

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        if (
            call.transform_id != native_transform.id
            or call.semantic != native_transform.semantic
            or call.input_ports != native_transform.inputs
            or call.output_ports != native_transform.outputs
        ):
            msg = "lowered host implementation received another transform call"
            raise ValueError(msg)
        try:
            point = point_refs[call.logical_point_id]
        except KeyError as error:
            msg = "host transform call references a point outside its batch context"
            raise ValueError(msg) from error
        if call.point_index != point.ordinal:
            msg = "host transform call point index does not match its SDK reference"
            raise ValueError(msg)
        return implementation.kernel(
            DomainHostTransformCall(
                transform=transform,
                point=point,
                inputs=call.inputs,
            )
        )

    return HostMeasurementTransformImplementation(
        id=implementation.id,
        semantic_id=implementation.semantic_id,
        semantic_version=implementation.semantic_version,
        rate=implementation.rate,
        implementation_fingerprint=implementation.implementation_fingerprint,
        validate_transform=validate,
        kernel=kernel,
    )


def lower_domain_host_transform_binding_internal(
    context: DomainBatchContext,
    binding: DomainHostTransformBinding,
) -> tuple[MeasurementTransformDef, HostMeasurementTransformImplementation]:
    """Lower one complete SDK host binding as a consistent native pair."""

    if not isinstance(cast("object", binding), DomainHostTransformBinding):
        msg = "domain host binding lowering requires DomainHostTransformBinding"
        raise TypeError(msg)
    transform = lower_domain_measurement_transform_internal(
        context,
        binding.transform,
    )
    implementation = lower_domain_host_transform_implementation_internal(
        context,
        binding.transform,
        binding.implementation,
    )
    return transform, implementation


def _lower_input_port(
    context: DomainBatchContext,
    port: DomainTransformInputPort,
) -> MeasurementTransformInputPort:
    use_id, product = _native_product_contract(context, port.product_use)
    return MeasurementTransformInputPort(port.id, use_id, product)


def _lower_output_port(
    context: DomainBatchContext,
    port: DomainTransformOutputPort,
) -> MeasurementTransformOutputPort:
    product = _native_product_def(context, port.product)
    use_ids = tuple(
        _native_product_contract(context, product_use)[0]
        for product_use in port.product_uses
    )
    return MeasurementTransformOutputPort(port.id, use_ids, product)


def _native_product_contract(
    context: DomainBatchContext,
    product_use: DomainProductUseRef,
) -> tuple[ProductUseId, ProductDef]:
    if not any(product_use is owned for owned in context.product_uses):
        msg = "domain transform port references a product use outside its context"
        raise ValueError(msg)
    linked_points = context_linked_points_internal(context)
    use_id = product_use_id_internal(product_use)
    try:
        use = next(
            use for use in linked_points.linked_plan.product_uses if use.id == use_id
        )
        product = next(
            product
            for product in linked_points.linked_plan.product_defs
            if product.id == use.product_id
        )
    except StopIteration as error:
        msg = "domain batch context lost its linked product contract"
        raise AssertionError(msg) from error
    return use_id, product


def _native_product_def(
    context: DomainBatchContext,
    contract: DomainProductContractView,
) -> ProductDef:
    linked_points = context_linked_points_internal(context)
    try:
        return next(
            product
            for product in linked_points.linked_plan.product_defs
            if product.id.qualified_name == contract.id
        )
    except StopIteration as error:
        msg = "domain batch context lost its linked product contract"
        raise AssertionError(msg) from error


def _require_context(context: DomainBatchContext) -> None:
    if not isinstance(cast("object", context), DomainBatchContext):
        msg = "domain transform lowering requires a DomainBatchContext"
        raise TypeError(msg)


__all__ = [
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainMeasurementTransform",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
    "DomainTransformRate",
    "MeasurementTransformSemanticContract",
]
