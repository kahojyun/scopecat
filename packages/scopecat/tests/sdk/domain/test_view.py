from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.planning.authoring import resolve_experiment
from scopecat.sdk.domain import (
    DomainExecutionOffer,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
)
from scopecat.sdk.domain._bridge import project_domain_plan
from tests.testkit.authoring import load_config


def test_domain_batch_view_materializes_typed_inputs_results_and_batches(
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
        module.template("test.domain.view", kind="domain_view")
        .domain(execution)
        .scan(count, (1, 3, 5))
        .record_product("counts")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    linked = link_verified_program(resolved.verified_program, resolved.environment)
    linked_points = materialize_linked_points(linked)

    projection = project_domain_plan(linked_points)
    full = projection.view(linked_points)
    selected = full.require_execution(
        dialect_id="test.domain",
        dialect_version="1",
    )
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

    offer = DomainExecutionOffer(max_points_per_batch=8)
    assert offer.max_points_per_batch == 8

    batch = MaterializedLinkedPointBatch(linked_points, (1, 2))
    batch_view = projection.view(batch)
    batched = batch_view.require_execution(dialect_id="test.domain")
    assert batched.input_values("count") == (3, 5)
    assert [point.logical_ordinal for point in batched.points] == [1, 2]
    assert all(
        selected_ref is full_ref
        for selected_ref, full_ref in zip(
            batch_view.points,
            full.points[1:],
            strict=True,
        )
    )
    assert all(
        point.ref is ref
        for point, ref in zip(batched.points, batch_view.points, strict=True)
    )
    assert batch_view.product_uses == full.product_uses
    assert batch_view.product_uses[0] is product_use


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
