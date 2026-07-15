from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.planning.authoring import resolve_experiment
from scopecat.sdk.domain import (
    DomainBatchContext,
    DomainExecutionOffer,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
)
from scopecat.sdk.domain._bridge import (
    DomainPlanProjection,
    make_domain_batch_context,
    project_domain_plan,
)
from tests.testkit.authoring import load_config


def _domain_scenario(
    tmp_path: Path,
    *,
    namespace: str,
    call_id: str,
    record_raw: bool = True,
) -> tuple[MaterializedLinkedPoints, DomainPlanProjection]:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.point(f"{namespace}_count", count_type)
    program = sc.domain_program(
        "program",
        dialect_id="test.context",
        dialect_version="1",
        body=object(),
        inputs={"count": count_type},
        results={
            "raw": ("raw", "v1"),
        },
    )
    call = sc.domain_call(
        call_id,
        program,
        inputs={"count": count},
        results={"raw": "raw"},
    )
    transform = sc.measurement_transform(
        "summarize",
        semantic=sc.MeasurementTransformSemanticContract(
            id="test.context.summarize",
            version="1",
            portability="host_only",
        ),
        inputs={"raw": "raw"},
        outputs={"summary": "summary"},
    )
    module = (
        sc.module(f"test.sdk.context.{namespace}")
        .product("raw", "summary", unit="count", dtype="int64")
        .domain_calls(call)
        .measurement_transforms(transform)
        .build()
    )
    template_builder = module.template(
        f"test.sdk.context.{namespace}", kind="domain_context"
    ).scan(count, (1, 3, 5))
    if record_raw:
        template_builder = template_builder.record_product("raw")
    template = template_builder.record_product("summary").build()
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    linked = link_verified_program(resolved.verified_program, resolved.environment)
    linked_points = materialize_linked_points(linked)
    return linked_points, project_domain_plan(linked_points)


def test_transform_input_remains_demanded_when_direct_product_is_not_recorded(
    tmp_path: Path,
) -> None:
    linked_points, projection = _domain_scenario(
        tmp_path,
        namespace="hidden-input",
        call_id="execute",
        record_raw=False,
    )
    program = linked_points.linked_plan.program
    [call] = program.domain_calls
    [transform] = program.measurement_transforms
    [direct_result] = call.results
    [transform_input] = transform.inputs
    [transform_output] = transform.outputs

    assert direct_result.product_use_ids == (transform_input.product_use_id,)
    assert transform_output.product_use_ids
    recorded_use_ids = {record.product_use_id for record in program.record_uses}
    assert transform_input.product_use_id not in recorded_use_ids
    assert set(transform_output.product_use_ids) == recorded_use_ids

    view = projection.view(linked_points)
    call_view = view.require_one_call(dialect_id="test.context")
    offer = DomainExecutionOffer.for_call(call_view)
    context = make_domain_batch_context(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1, 2)),
        offer,
        adapter_id="test.hidden-input",
        batch_ordinal=0,
    )

    [projected_transform] = context.measurement_transforms
    assert context.direct_product_uses == (projected_transform.inputs[0].product_use,)
    assert projected_transform.outputs[0].product_uses


def test_domain_batch_context_scopes_offer_points_and_product_uses(
    tmp_path: Path,
) -> None:
    linked_points, projection = _domain_scenario(
        tmp_path,
        namespace="owned",
        call_id="execute",
    )
    full = projection.view(linked_points)
    call = full.require_one_call(dialect_id="test.context")
    raw_uses = call.result("raw").product_uses
    [transform] = call.measurement_transforms
    [summary_use] = transform.outputs[0].product_uses
    offer = DomainExecutionOffer.for_call(
        call,
        max_points_per_batch=2,
    )
    batch = MaterializedLinkedPointBatch(linked_points, (1, 2))

    context = make_domain_batch_context(
        projection,
        batch,
        offer,
        adapter_id="test.adapter",
        batch_ordinal=4,
    )

    assert isinstance(context, DomainBatchContext)
    assert context.batch_ordinal == 4
    assert context.call.id == "execute"
    assert context.call.input_values("count") == (3, 5)
    assert context.product_uses == full.product_uses
    assert context.direct_product_uses == raw_uses
    assert context.derived_product_uses == (summary_use,)
    assert context.measurement_transforms == (transform,)
    assert summary_use in context.product_uses
    assert all(isinstance(point, DomainPointRef) for point in context.points)
    assert all(
        selected is full_point
        for selected, full_point in zip(
            context.points,
            full.points[1:],
            strict=True,
        )
    )
    assert all(
        point.ref is ref
        for point, ref in zip(context.call.points, context.points, strict=True)
    )
    assert all(
        isinstance(product_use, DomainProductUseRef)
        for product_use in context.product_uses
    )

    preparation = context.new_preparation()
    assert isinstance(preparation, DomainPreparationBuilder)
    assert preparation.context is context


def test_domain_plan_projection_rejects_foreign_offer_and_points(
    tmp_path: Path,
) -> None:
    linked_points, projection = _domain_scenario(
        tmp_path,
        namespace="owned",
        call_id="execute",
    )
    foreign_points, foreign_projection = _domain_scenario(
        tmp_path,
        namespace="foreign",
        call_id="foreign_execute",
    )
    view = projection.view(linked_points)
    call = view.require_one_call(dialect_id="test.context")
    offer = DomainExecutionOffer.for_call(call)
    batch = MaterializedLinkedPointBatch(linked_points, (0, 1))

    foreign_view = foreign_projection.view(foreign_points)
    foreign_call = foreign_view.require_one_call(dialect_id="test.context")
    foreign_offer = DomainExecutionOffer.for_call(
        foreign_call,
    )
    with pytest.raises(ValueError, match="does not identify exactly one call"):
        make_domain_batch_context(
            projection,
            batch,
            foreign_offer,
            adapter_id="test.adapter",
            batch_ordinal=0,
        )

    with pytest.raises(ValueError, match="points from its materialized plan"):
        projection.view(foreign_points)

    foreign_batch = MaterializedLinkedPointBatch(foreign_points, (0, 1))
    with pytest.raises(ValueError, match="points from its materialized plan"):
        make_domain_batch_context(
            projection,
            foreign_batch,
            offer,
            adapter_id="test.adapter",
            batch_ordinal=0,
        )

    assert all(
        owned is not foreign
        for owned, foreign in zip(
            projection.point_refs,
            foreign_projection.point_refs,
            strict=True,
        )
    )
    assert all(
        owned is not foreign
        for owned, foreign in zip(
            projection.product_use_refs,
            foreign_projection.product_use_refs,
            strict=True,
        )
    )


def test_domain_execution_offer_rejects_invalid_batch_capacity(
    tmp_path: Path,
) -> None:
    linked_points, projection = _domain_scenario(
        tmp_path,
        namespace="offer",
        call_id="execute",
    )
    call = projection.view(linked_points).require_one_call(dialect_id="test.context")

    with pytest.raises(ValueError, match="must be positive"):
        DomainExecutionOffer.for_call(
            call,
            max_points_per_batch=0,
        )
