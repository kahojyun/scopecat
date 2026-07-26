from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.compiler.linking.linked import (
    materialize_linked_points,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.program import core_domain_executions
from scopecat.sdk.domain import (
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from tests.testkit.authoring import link_invocation, load_config


def test_domain_batch_request_exposes_complete_inputs_and_call_contract(
    tmp_path: Path,
) -> None:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.coordinate("count", count_type)
    body = object()
    program = sc.domain_program(
        "program/variant",
        dialect_id="test.domain",
        dialect_version="1",
        body=body,
        inputs={"count": count_type},
        results={"counts": ("counts", "v1")},
    )
    module = sc.module_body(id="test.domain.view").product(
        "counts", unit="count", dtype="int64"
    )
    execution = sc.domain_execution(
        program,
        id="execution",
        inputs={"count": count},
        results={"counts": module.products["counts"]},
    )
    module_call = module.domain(execution).build()()
    experiment_body = (
        sc.experiment(module_call)
        .scan(count, (1, 3, 5))
        .record_product(module_call.products.counts, record_id="counts")
    )
    template = sc.template(id="test.domain.view", kind="domain_view")(
        lambda: experiment_body
    )
    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    linked = resolved
    linked_points = materialize_linked_points(linked)

    execution_id = core_domain_executions(linked.program)[0].id
    closure = domain_result_closure(linked.program, execution_id)
    call = make_domain_call_view(
        linked,
        execution_id,
        closure,
    )
    full = make_domain_batch_request(
        call,
        linked_points,
        (0, 1, 2),
        batch_ordinal=0,
    )
    assert full.call.program.id == "program%2Fvariant"
    assert full.call.program.dialect_id == "test.domain"
    assert full.call.program.dialect_version == "1"
    assert full.call.program.body is body
    assert full.inputs.program.input("count") == (1, 3, 5)
    assert all(isinstance(point, DomainPointRef) for point in full.points)
    assert [point.ordinal for point in full.points] == [0, 1, 2]

    result = full.call.result("counts")
    assert result.contract == ("counts", "v1")
    assert result.product.unit == "count"
    assert result.product.dtype == "int64"
    product_use = result.require_one_product_use()
    assert isinstance(product_use, DomainProductUseRef)
    assert product_use.id == linked.program.product_uses[0].id.value
    assert product_use.product is result.product
    assert product_use is full.product_uses[0]

    batch = make_domain_batch_request(
        call,
        linked_points,
        (1, 2),
        batch_ordinal=1,
    )
    assert batch.inputs.program.input("count") == (3, 5)
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
