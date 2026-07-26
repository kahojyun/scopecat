from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.program import core_domain_executions
from scopecat.sdk.domain import (
    DomainBatchContext,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    MeasurementTransformSemanticContract,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_template,
)
from tests.testkit.authoring import link_invocation, load_config


def _domain_scenario(
    tmp_path: Path,
    *,
    namespace: str,
    record_raw: bool = True,
) -> MaterializedLinkedPoints:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.coordinate(f"{namespace}_count", count_type)
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
    transform = sc.measurement_transform(
        "summarize",
        semantic=MeasurementTransformSemanticContract(
            id="test.context.summarize",
            version="1",
        ),
        inputs={"raw": "raw"},
        outputs={"summary": "summary"},
    )
    module = (
        sc.module_body(id=f"test.sdk.context.{namespace}")
        .product("raw", "summary", unit="count", dtype="int64")
        .measurement_transforms(transform)
    )
    execution = sc.domain_execution(
        program,
        inputs={"count": count},
        results={"raw": module.products["raw"]},
    )
    module_call = module.domain(execution).build()()
    body = sc.experiment(module_call).scan(count, (1, 3, 5))
    if record_raw:
        body = body.record_product(module_call.products.raw, record_id="raw")
    body = body.record_product(module_call.products.summary, record_id="summary")
    template = sc.template(
        id=f"test.sdk.context.{namespace}",
        kind="domain_context",
    )(lambda: body)
    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    linked = resolved
    linked_points = materialize_linked_points(linked)
    return linked_points


def _batch_context(
    linked_points: MaterializedLinkedPoints,
    point_ordinals: tuple[int, ...],
    *,
    batch_ordinal: int = 0,
    absorbed_input_ids: tuple[str, ...] = (),
) -> DomainBatchContext:
    program = linked_points.linked_plan.program
    execution = core_domain_executions(program)[0]
    request = make_domain_compile_template(
        linked_points.linked_plan,
        execution.id,
        domain_result_closure(program, execution.id),
    ).bind_coverage(
        (tuple(range(len(linked_points.point_domain.points))),),
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution.id,
            "program",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution.id,
            "compiler",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    return make_domain_batch_context(
        request,
        linked_points,
        point_ordinals,
        batch_ordinal=batch_ordinal,
        absorbed_input_ids=absorbed_input_ids,
    )


def test_transform_input_remains_demanded_when_direct_product_is_not_recorded(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="hidden-input",
        record_raw=False,
    )
    program = linked_points.linked_plan.program
    call = core_domain_executions(program)[0]
    [transform] = program.measurement_transforms
    [direct_result] = call.results
    [transform_input] = transform.inputs
    [transform_output] = transform.outputs

    assert direct_result.product_use_ids == (transform_input.product_use_id,)
    assert transform_output.product_use_ids
    recorded_use_ids = {record.product_use_id for record in program.record_uses}
    assert transform_input.product_use_id not in recorded_use_ids
    assert set(transform_output.product_use_ids) == recorded_use_ids

    context = _batch_context(
        linked_points,
        (0, 1, 2),
    )

    [projected_transform] = context.measurement_transforms
    assert context.direct_product_uses == (projected_transform.inputs[0].product_use,)
    assert projected_transform.outputs[0].product_uses


def test_domain_batch_context_scopes_offer_points_and_product_uses(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="owned",
    )
    program = linked_points.linked_plan.program
    [transform] = program.measurement_transforms
    full = _batch_context(
        linked_points,
        (0, 1, 2),
    )
    execution = full.execution
    raw_uses = execution.result("raw").product_uses
    [transform] = execution.measurement_transforms
    [summary_use] = transform.outputs[0].product_uses
    context = _batch_context(
        linked_points,
        (1, 2),
        batch_ordinal=4,
    )

    assert isinstance(context, DomainBatchContext)
    assert context.batch_ordinal == 4
    assert context.execution.input_values("count") == (3, 5)
    assert tuple(use.id for use in context.product_uses) == tuple(
        use.id for use in full.product_uses
    )
    assert tuple(use.id for use in context.direct_product_uses) == tuple(
        use.id for use in raw_uses
    )
    assert tuple(use.id for use in context.derived_product_uses) == (summary_use.id,)
    assert tuple(item.id for item in context.measurement_transforms) == (transform.id,)
    assert summary_use.id in {use.id for use in context.product_uses}
    assert all(isinstance(point, DomainPointRef) for point in context.points)
    assert all(
        (selected.id, selected.ordinal) == (full_point.id, full_point.ordinal)
        for selected, full_point in zip(
            context.points,
            full.points[1:],
            strict=True,
        )
    )
    assert all(
        point.ref is ref
        for point, ref in zip(context.execution.points, context.points, strict=True)
    )
    assert all(
        isinstance(product_use, DomainProductUseRef)
        for product_use in context.product_uses
    )

    preparation = context.new_preparation()
    assert isinstance(preparation, DomainPreparationBuilder)
    assert preparation.context is context


def test_absorbed_inputs_are_not_reexposed_during_preparation(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="absorbed-input",
    )
    context = _batch_context(
        linked_points,
        (0, 1, 2),
        absorbed_input_ids=("count",),
    )

    assert context.execution.program.inputs == ()
    assert all(point.inputs == () for point in context.execution.points)
    with pytest.raises(KeyError):
        context.execution.input_values("count")


def test_domain_batch_context_owns_fresh_sdk_refs(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="owned",
    )
    foreign_points = _domain_scenario(
        tmp_path,
        namespace="foreign",
    )
    context = _batch_context(
        linked_points,
        (0, 1),
    )
    foreign = _batch_context(
        foreign_points,
        (0, 1),
    )

    assert all(
        owned is not foreign
        for owned, foreign in zip(
            context.points,
            foreign.points,
            strict=True,
        )
    )
    assert all(
        owned is not foreign
        for owned, foreign in zip(
            context.product_uses,
            foreign.product_uses,
            strict=True,
        )
    )
