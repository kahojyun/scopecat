from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.compiler.linking.linked import (
    LinkedPointMaterializer,
    link_verified_program,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.planning.authoring import resolve_experiment
from scopecat.sdk.domain import (
    DomainIterationLeaf,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_request,
)
from tests.testkit.authoring import load_config


def test_domain_batch_context_materializes_only_selected_residual_inputs(
    tmp_path: Path,
) -> None:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.point("count", count_type)
    body = object()
    program = sc.domain_program(
        "program",
        dialect_id="test.domain",
        dialect_version="1",
        body=body,
        inputs={"count": count_type},
        results={"counts": ("counts", "v1")},
    )
    module = (
        sc.module("test.domain.view")
        .product("counts", unit="count", dtype="int64")
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"count": count},
        results={"counts": module.products["counts"]},
    )
    template = (
        module.domain(execution)
        .template("test.domain.view", kind="domain_view")
        .scan(count, (1, 3, 5))
        .record_product("counts")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    linked = link_verified_program(resolved.verified_program, resolved.environment)
    materializer = LinkedPointMaterializer(linked)
    linked_points = materializer.materialize()

    closure = domain_result_closure(linked.program, execution.id)
    request = make_domain_compile_request(
        linked,
        execution.id,
        closure,
        ((0, 1, 2),),
        lambda input_ids, ordinals, max_points: materializer.bind_domain_inputs(
            execution.id,
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    layout = request.iteration_layout
    assert layout is not None
    assert isinstance(layout.root, DomainIterationLeaf)
    assert layout.root.extent == 3
    assert layout.root.axis_ids == ("count",)
    count_axis = request.point_axis("count")
    assert count_axis is not None
    assert count_axis.values == (1, 3, 5)
    full = make_domain_batch_context(
        request,
        linked_points,
        (0, 1, 2),
        batch_ordinal=0,
    )
    selected = full.execution
    assert selected.program.dialect_id == "test.domain"
    assert selected.program.dialect_version == "1"
    assert selected.program.body is body
    assert selected.input_values("count") == (1, 3, 5)
    assert all(isinstance(point, DomainPointRef) for point in full.points)
    assert [point.ordinal for point in full.points] == [0, 1, 2]
    assert tuple(point.ref for point in selected.points) == full.points
    assert all(
        point.ref is ref
        for point, ref in zip(selected.points, full.points, strict=True)
    )

    result = selected.result("counts")
    assert result.contract == ("counts", "v1")
    assert result.product.unit == "count"
    assert result.product.dtype == "int64"
    product_use = result.require_one_product_use()
    assert isinstance(product_use, DomainProductUseRef)
    assert product_use.id == linked.product_uses[0].id.value
    assert product_use.product is result.product
    assert product_use is full.product_uses[0]

    batch = make_domain_batch_context(
        request,
        linked_points,
        (1, 2),
        batch_ordinal=1,
    )
    batched = batch.execution
    assert batched.input_values("count") == (3, 5)
    assert [point.logical_ordinal for point in batched.points] == [1, 2]
    assert all(
        (selected_ref.id, selected_ref.ordinal) == (full_ref.id, full_ref.ordinal)
        for selected_ref, full_ref in zip(
            batch.points,
            full.points[1:],
            strict=True,
        )
    )
    assert all(
        point.ref is ref
        for point, ref in zip(batched.points, batch.points, strict=True)
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
        kind="observable",
        unit="count",
        dtype="int64",
        axes=(
            DomainProductAxisView(
                id="shot",
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
