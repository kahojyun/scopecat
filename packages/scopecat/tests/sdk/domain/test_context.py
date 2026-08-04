from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import scopecat as sc
from scopecat.measurements.results import MeasurementScalar, MeasurementValue
from scopecat.planning.domain_bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from scopecat.planning.domain_results import domain_result_product_use_ids
from scopecat.planning.point_materialization import (
    MaterializedBoundPoints,
    materialize_bound_points,
)
from scopecat.program.domain import domain_program
from scopecat.program.products import ModuleProductDecl
from scopecat.sdk.domain import (
    DomainBatchRequest,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
)
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.domain import domain_call


@dataclass(frozen=True, slots=True)
class _DomainProducts:
    raw: sc.ProductRef
    summary: sc.ProductRef


def _domain_scenario(
    tmp_path: Path,
    *,
    namespace: str,
    record_raw: bool = True,
) -> MaterializedBoundPoints:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.coordinate(f"{namespace}_count", count_type)
    program = domain_program(
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

    @sc.module(id=f"test.sdk.context.{namespace}")
    def domain_module(
        module: sc.ModuleContext,
        count_input: Annotated[sc.Input[int], sc.IntType(minimum=0)],
    ) -> _DomainProducts:
        summary = module._product("summary", unit="count", dtype="int64")
        call = domain_call(
            program,
            inputs={"count": sc.input_ref(count_input)},
            products={
                "raw": ModuleProductDecl(
                    "raw",
                    unit="count",
                    dtype="int64",
                )
            },
        )
        module._postprocess(
            "summarize",
            input=call.results.raw,
            outputs={"summary": summary},
            kernel=summarize,
        )
        module.use(call)
        return _DomainProducts(raw=call.results.raw, summary=summary)

    @sc.experiment(
        id=f"test.sdk.context.{namespace}",
        kind="domain_context",
    )
    def template(experiment: sc.ExperimentContext) -> None:
        products = experiment.use(domain_module(count_input=count))
        experiment.grid(sc.axis(count, (1, 3, 5)))
        if record_raw:
            experiment.record(products.raw, record_id="raw")
        experiment.record(products.summary, record_id="summary")

    resolved = bind_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    bound = resolved
    bound_points = materialize_bound_points(bound)
    return bound_points


def _batch_context(
    bound_points: MaterializedBoundPoints,
    point_ordinals: tuple[int, ...],
    *,
    batch_ordinal: int = 0,
) -> DomainBatchRequest:
    bound = bound_points.bound_plan
    execution = bound.program.program.domain_executions[0]
    call = make_domain_call_view(
        bound,
        execution.id,
        domain_result_product_use_ids(bound.bindings, execution),
    )
    return make_domain_batch_request(
        call,
        bound_points,
        point_ordinals,
        batch_ordinal=batch_ordinal,
    )


def test_postprocessor_input_remains_a_direct_domain_result_when_not_recorded(
    tmp_path: Path,
) -> None:
    bound_points = _domain_scenario(
        tmp_path,
        namespace="hidden-input",
        record_raw=False,
    )
    bound = bound_points.bound_plan
    program = bound.bindings
    call = bound.program.program.domain_executions[0]
    [postprocessor] = program.measurement_postprocessors
    [direct_result] = call.results
    [postprocessor_output] = postprocessor.outputs

    assert program.domain_result_use_ids[(call.id, direct_result[0])] == (
        postprocessor.input_product_use_id,
    )
    assert postprocessor_output.product_use_ids
    recorded_use_ids = {record.product_use_id for record in program.product_record_uses}
    assert postprocessor.input_product_use_id not in recorded_use_ids
    assert set(postprocessor_output.product_use_ids) == recorded_use_ids

    context = _batch_context(
        bound_points,
        (0, 1, 2),
    )

    assert tuple(use.id for use in context.product_uses) == (
        postprocessor.input_product_use_id.value,
    )


def test_domain_batch_request_scopes_points_inputs_and_product_uses(
    tmp_path: Path,
) -> None:
    bound_points = _domain_scenario(
        tmp_path,
        namespace="owned",
    )
    full = _batch_context(
        bound_points,
        (0, 1, 2),
    )
    raw_uses = full.call.result("raw").product_uses
    context = _batch_context(
        bound_points,
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
    bound_points = _domain_scenario(
        tmp_path,
        namespace="owned",
    )
    foreign_points = _domain_scenario(
        tmp_path,
        namespace="foreign",
    )
    context = _batch_context(
        bound_points,
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
