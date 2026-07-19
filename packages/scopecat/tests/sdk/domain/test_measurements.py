from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.measurements.host_transforms import HostMeasurementTransformCall
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    point_id,
    product_use_id,
    project_domain_plan,
)
from scopecat.sdk.domain._measurement_bridge import (
    lower_domain_host_transform_binding,
    lower_domain_measurement_transform,
)
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.measurements import (
    DomainHostTransformBinding,
    DomainHostTransformCall,
    DomainHostTransformImplementation,
    DomainMeasurementTransform,
)
from tests.testkit.authoring import load_config


def _context(tmp_path: Path, *, namespace: str) -> DomainBatchContext:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.point(f"{namespace}_count", count_type)
    program = sc.domain_program(
        "program",
        dialect_id="test.sdk.measurements",
        dialect_version="1",
        body=object(),
        inputs={"count": count_type},
        results={"raw": ("raw", "v1")},
    )
    transform = sc.measurement_transform(
        "summarize",
        semantic=MeasurementTransformSemanticContract(
            id="test.summarize",
            version="1",
            portability="host_only",
        ),
        inputs={"raw": "raw"},
        outputs={"summary": "summary"},
    )
    module = (
        sc.module(f"test.sdk.measurements.{namespace}")
        .product("raw", "summary", unit="count", dtype="int64")
        .measurement_transforms(transform)
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"count": count},
        results={"raw": module.products["raw"]},
    )
    template = (
        module.template(
            f"test.sdk.measurements.{namespace}",
            kind="domain_measurements",
        )
        .domain(execution)
        .scan(count, (1, 3))
        .record_product("raw")
        .record_product("summary")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    linked_points = materialize_linked_points(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    projection = project_domain_plan(linked_points, execution.id)
    return make_domain_batch_context(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1)),
        compiler_id=f"test.sdk.measurements.{namespace}",
        batch_ordinal=0,
    )


def _transform(context: DomainBatchContext) -> DomainMeasurementTransform:
    [transform] = context.measurement_transforms
    return transform


def test_domain_transform_lowering_recovers_exact_native_contracts(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, namespace="lower")
    transform = _transform(context)

    native = lower_domain_measurement_transform(context, transform)

    assert native.id.value == transform.id
    assert native.rate == "point"
    assert native.inputs[0].product_use_id == product_use_id(
        transform.inputs[0].product_use
    )
    assert native.outputs[0].product_use_ids == tuple(
        product_use_id(product_use) for product_use in transform.outputs[0].product_uses
    )
    assert native.inputs[0].product.id.qualified_name == transform.inputs[0].product.id
    assert native.outputs[0].product.id.qualified_name == (
        transform.outputs[0].product.id
    )


def test_lowered_host_kernel_recovers_original_context_point_ref(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, namespace="kernel")
    transform = _transform(context)
    validated: list[DomainMeasurementTransform] = []
    calls: list[DomainHostTransformCall] = []

    def validate(candidate: DomainMeasurementTransform) -> None:
        validated.append(candidate)

    def kernel(call: DomainHostTransformCall):
        calls.append(call)
        return {"summary": Quantity(2, "count")}

    binding = DomainHostTransformBinding(
        transform,
        DomainHostTransformImplementation(
            id="test.summarize.python",
            semantic_id=transform.semantic.id,
            semantic_version=transform.semantic.version,
            implementation_fingerprint="test.summarize.python.v1",
            validate_transform=validate,
            kernel=kernel,
        ),
    )
    native_transform, native_implementation = lower_domain_host_transform_binding(
        context, binding
    )

    native_implementation.validate_transform(native_transform)
    point = context.points[1]
    outputs = native_implementation.kernel(
        HostMeasurementTransformCall(
            transform_id=native_transform.id,
            semantic=native_transform.semantic,
            logical_point_id=point_id(point),
            point_index=point.ordinal,
            input_ports=native_transform.inputs,
            output_ports=native_transform.outputs,
            inputs={"raw": Quantity(3, "count")},
        )
    )

    assert validated == [transform]
    assert len(calls) == 1
    assert calls[0].point is point
    assert calls[0].transform is transform
    assert calls[0].point_index == point.ordinal
    assert outputs == {"summary": Quantity(2, "count")}


def test_domain_transform_lowering_rejects_foreign_product_ref(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, namespace="owned")
    foreign = _context(tmp_path, namespace="foreign")

    with pytest.raises(ValueError, match="outside its context"):
        lower_domain_measurement_transform(context, _transform(foreign))
