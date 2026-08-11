from __future__ import annotations

from pathlib import Path

from testkit.authoring import bind_invocation, load_config
from testkit.domain import domain_call

import scopecat as sc
from scopecat.planning.domain_bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from scopecat.planning.domain_results import domain_result_product_use_ids
from scopecat.planning.point_materialization import (
    materialize_bound_points,
)
from scopecat.program.domain import domain_program
from scopecat.program.products import (
    ModuleProductDecl,
    ProductValueSpec,
    product_axis,
)
from scopecat.sdk.domain import (
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
)


def test_domain_batch_request_exposes_complete_inputs_and_call_contract(
    tmp_path: Path,
) -> None:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.coordinate("count", count_type)
    body = object()
    program = domain_program(
        "program/variant",
        dialect_id="test.domain",
        dialect_version="1",
        body=body,
        inputs={"count": count_type},
        results={"counts": ("counts", "v1")},
    )

    authored_call = domain_call(
        program,
        id="execution",
        inputs={"count": count},
        products={
            "counts": ModuleProductDecl(
                "counts",
                value_spec=ProductValueSpec(
                    unit="count",
                    dtype="int64",
                    axes=(
                        product_axis(
                            "shot",
                            size=8,
                            kind="shot",
                            shared_as="shot",
                        ),
                    ),
                ),
            )
        },
    )

    @sc.experiment(id="test.domain.view", kind="domain_view")
    def experiment(experiment: sc.ExperimentContext) -> None:
        results = experiment.use(authored_call)
        experiment.grid(sc.axis(count, (1, 3, 5)))
        experiment.alias(results.counts, record_id="counts")

    resolved = bind_invocation(
        experiment.bind(),
        config_profile=load_config(),
    )
    bound = resolved
    bound_points = materialize_bound_points(bound)

    execution = bound.program.program.domain_executions[0]
    execution_id = execution.id
    product_use_ids = domain_result_product_use_ids(bound.bindings, execution)
    call_view = make_domain_call_view(
        bound,
        execution_id,
        product_use_ids,
    )
    full = make_domain_batch_request(
        call_view,
        bound_points,
        (0, 1, 2),
        batch_ordinal=0,
    )
    assert full.call.program.id == "program%2Fvariant"
    assert full.call.program.dialect_id == "test.domain"
    assert full.call.program.dialect_version == "1"
    assert full.call.program.body is body
    assert full.inputs.program_input("count") == (1, 3, 5)
    assert all(isinstance(point, DomainPointRef) for point in full.points)
    assert [point.ordinal for point in full.points] == [0, 1, 2]

    result = full.call.result("counts")
    assert result.contract == ("counts", "v1")
    assert result.product.unit == "count"
    assert result.product.dtype == "int64"
    assert result.product.axes[0].id == "shot"
    assert result.product.axes[0].dimension_id == "shared/execution/shot"
    assert result.product.axes[0].dimension_label == "shot"
    product_use = result.require_one_product_use()
    assert isinstance(product_use, DomainProductUseRef)
    assert product_use.id == bound.bindings.product_uses[0].id.value
    assert product_use.product is result.product
    assert product_use is full.product_uses[0]

    batch = make_domain_batch_request(
        call_view,
        bound_points,
        (1, 2),
        batch_ordinal=1,
    )
    assert batch.inputs.program_input("count") == (3, 5)
    assert [point.ordinal for point in batch.points] == [1, 2]
    assert all(
        (selected_ref.id, selected_ref.ordinal) == (full_ref.id, full_ref.ordinal)
        for selected_ref, full_ref in zip(
            batch.points,
            full.points[1:],
            strict=True,
        )
    )
    assert tuple(use.id for use in batch.product_uses) == tuple(
        use.id for use in full.product_uses
    )
    assert batch.product_uses[0].id == product_use.id


def test_domain_product_contract_view_recursively_snapshots_metadata() -> None:
    metadata = {"labels": ["raw"]}
    axis_metadata = {"role": {"name": "shot"}}

    contract = DomainProductContractView(
        id="capture/counts",
        unit="count",
        dtype="int64",
        axes=(
            DomainProductAxisView(
                id="shot",
                dimension_id="product/capture/counts/shot",
                dimension_label="shot",
                kind="shot",
                size=8,
                metadata=axis_metadata,
            ),
        ),
        metadata=metadata,
    )
    metadata["labels"].append("mutated")
    axis_metadata["role"]["name"] = "mutated"

    assert contract.metadata == {"labels": ("raw",)}
    assert contract.axes[0].metadata == {"role": {"name": "shot"}}
