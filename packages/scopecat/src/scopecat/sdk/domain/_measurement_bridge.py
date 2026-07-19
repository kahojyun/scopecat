"""Core lowering for public domain measurement-transform bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.host_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformImplementation,
)
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    MeasurementTransformInputPort,
    MeasurementTransformOutputPort,
    NativeMeasurementTransformId,
)
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.domain._bridge import point_id, product_use_id
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.measurements import (
    DomainHostTransformBinding,
    DomainHostTransformCall,
    DomainHostTransformImplementation,
)
from scopecat.sdk.domain.view import (
    DomainMeasurementTransform,
    DomainProductContractView,
    DomainProductUseRef,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)


def lower_domain_measurement_transform(
    context: DomainBatchContext,
    transform: DomainMeasurementTransform,
) -> MeasurementTransformDef:
    """Lower one context-owned SDK declaration into the core graph."""

    return MeasurementTransformDef(
        id=NativeMeasurementTransformId(transform.id),
        semantic=transform.semantic,
        inputs=tuple(
            _lower_input_port(context, port)
            for port in sorted(transform.inputs, key=lambda item: item.id)
        ),
        outputs=tuple(
            _lower_output_port(context, port)
            for port in sorted(transform.outputs, key=lambda item: item.id)
        ),
    )


def lower_domain_host_transform_implementation(
    context: DomainBatchContext,
    transform: DomainMeasurementTransform,
    implementation: DomainHostTransformImplementation,
) -> HostMeasurementTransformImplementation:
    """Adapt one SDK validator/kernel pair to the core host executor."""

    DomainHostTransformBinding(transform, implementation)
    native_transform = lower_domain_measurement_transform(context, transform)
    point_refs = {point_id(point): point for point in context.points}

    def validate(candidate: MeasurementTransformDef) -> None:
        if candidate != native_transform:
            msg = "lowered host implementation received another transform contract"
            raise ValueError(msg)
        implementation.validate_transform(transform)

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, Sequence[MeasurementValue]]:
        if (
            call.transform_id != native_transform.id
            or call.semantic != native_transform.semantic
            or call.input_ports != native_transform.inputs
            or call.output_ports != native_transform.outputs
        ):
            msg = "lowered host implementation received another transform call"
            raise ValueError(msg)
        try:
            points = tuple(point_refs[point.logical_id] for point in call.points)
        except KeyError as error:
            msg = "host transform call references a point outside its batch context"
            raise ValueError(msg) from error
        if tuple(point.ordinal for point in points) != tuple(
            point.logical_ordinal for point in call.points
        ):
            msg = "host transform call point order does not match its SDK references"
            raise ValueError(msg)
        return implementation.kernel(
            DomainHostTransformCall(
                transform=transform,
                points=points,
                inputs=call.inputs,
            )
        )

    return HostMeasurementTransformImplementation(
        id=implementation.id,
        semantic_id=implementation.semantic_id,
        semantic_version=implementation.semantic_version,
        implementation_fingerprint=implementation.implementation_fingerprint,
        validate_transform=validate,
        kernel=kernel,
    )


def lower_domain_host_transform_binding(
    context: DomainBatchContext,
    binding: DomainHostTransformBinding,
) -> tuple[MeasurementTransformDef, HostMeasurementTransformImplementation]:
    """Lower one complete SDK host binding as a consistent native pair."""

    transform = lower_domain_measurement_transform(context, binding.transform)
    implementation = lower_domain_host_transform_implementation(
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
    catalog = context.measurement_catalog
    use_id = product_use_id(product_use)
    try:
        use = next(use for use in catalog.product_uses if use.id == use_id)
        product = next(
            product for product in catalog.product_defs if product.id == use.product_id
        )
    except StopIteration as error:
        msg = "domain batch context lost its linked product contract"
        raise AssertionError(msg) from error
    return use_id, product


def _native_product_def(
    context: DomainBatchContext,
    contract: DomainProductContractView,
) -> ProductDef:
    catalog = context.measurement_catalog
    try:
        return next(
            product
            for product in catalog.product_defs
            if product.id.qualified_name == contract.id
        )
    except StopIteration as error:
        msg = "domain batch context lost its linked product contract"
        raise AssertionError(msg) from error
