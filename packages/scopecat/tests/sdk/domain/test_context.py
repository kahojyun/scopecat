from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.program import core_domain_executions
from scopecat.measurements.results import MeasurementScalar, MeasurementValue
from scopecat.sdk.domain import (
    DomainBatchRequest,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_request,
    make_domain_call_view,
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

    def summarize(_value: MeasurementValue) -> dict[str, MeasurementValue]:
        return {
            "summary": MeasurementScalar.create(
                dtype="int64",
                value=0,
                unit="count",
            )
        }

    postprocessor = sc.measurement_postprocessor(
        "summarize",
        input="raw",
        outputs={"summary": "summary"},
        kernel=summarize,
    )
    module = (
        sc.procedure(id=f"test.sdk.context.{namespace}")
        .product("raw", "summary", unit="count", dtype="int64")
        .measurement_postprocessors(postprocessor)
    )
    execution = sc.domain_execution(
        program,
        inputs={"count": count},
        results={"raw": module.products["raw"]},
    )
    module_call = module.domain(execution).build()()
    body = sc.experiment(module_call).scan(sc.axis(count, (1, 3, 5)))
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
) -> DomainBatchRequest:
    program = linked_points.linked_plan.program
    execution = core_domain_executions(program)[0]
    call = make_domain_call_view(
        linked_points.linked_plan,
        execution.id,
        domain_result_closure(program, execution.id),
    )
    return make_domain_batch_request(
        call,
        linked_points,
        point_ordinals,
        batch_ordinal=batch_ordinal,
    )


def test_postprocessor_input_remains_a_direct_domain_result_when_not_recorded(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="hidden-input",
        record_raw=False,
    )
    program = linked_points.linked_plan.program
    call = core_domain_executions(program)[0]
    [postprocessor] = program.measurement_postprocessors
    [direct_result] = call.results
    [postprocessor_output] = postprocessor.outputs

    assert direct_result.product_use_ids == (postprocessor.input_product_use_id,)
    assert postprocessor_output.product_use_ids
    recorded_use_ids = {record.product_use_id for record in program.record_uses}
    assert postprocessor.input_product_use_id not in recorded_use_ids
    assert set(postprocessor_output.product_use_ids) == recorded_use_ids

    context = _batch_context(
        linked_points,
        (0, 1, 2),
    )

    assert tuple(use.id for use in context.product_uses) == (
        postprocessor.input_product_use_id.value,
    )


def test_domain_batch_request_scopes_points_inputs_and_product_uses(
    tmp_path: Path,
) -> None:
    linked_points = _domain_scenario(
        tmp_path,
        namespace="owned",
    )
    full = _batch_context(
        linked_points,
        (0, 1, 2),
    )
    raw_uses = full.call.result("raw").product_uses
    context = _batch_context(
        linked_points,
        (1, 2),
        batch_ordinal=4,
    )

    assert isinstance(context, DomainBatchRequest)
    assert context.batch_ordinal == 4
    assert context.inputs.program_input("count") == (3, 5)
    assert tuple(use.id for use in context.product_uses) == tuple(
        use.id for use in full.product_uses
    )
    assert tuple(use.id for use in context.product_uses) == tuple(
        use.id for use in raw_uses
    )
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
        isinstance(product_use, DomainProductUseRef)
        for product_use in context.product_uses
    )

    preparation = DomainPreparationBuilder(context)
    assert isinstance(preparation, DomainPreparationBuilder)
    assert preparation.context is context


def test_domain_batch_request_owns_fresh_sdk_refs(
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
