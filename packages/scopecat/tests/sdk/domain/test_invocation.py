from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductAxisDef, ProductKind
from scopecat.compiler.typed.program import (
    TypedProgram,
    product_output,
    record_product,
    shot_axis,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.invocation import (
    AdapterEntryResults,
    ClosedDomainResultMapping,
    DomainOutputValue,
    EntryPointBinding,
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    ProductUseId,
    ResultUseBinding,
    SelectedDomainMeasurementOutputs,
    close_domain_invocation,
    materialize_linked_points,
    seal_domain_output_values,
    seal_domain_result_mapping,
    select_domain_measurement_outputs,
)
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import table_value_expr


def _linked_points(
    *,
    point_count: int = 3,
    product_count: int = 2,
    shared_product: bool = False,
    product_kind: ProductKind = "observable",
    product_dtype: MeasurementDType = "float64",
    product_unit: str | None = "ratio",
    product_axes: tuple[ProductAxisDef, ...] = (),
) -> MaterializedLinkedPoints:
    point_type = Table(
        columns=(TableColumn("x", Scalar(Float())),),
        min_rows=point_count,
        max_rows=point_count,
    )
    products = (
        (
            product_output(
                "shared-signal",
                kind=product_kind,
                unit=product_unit,
                dtype=product_dtype,
                axes=product_axes,
                metadata={"definition": "shared"},
            ),
        )
        if shared_product and product_count
        else tuple(
            product_output(
                f"signal-{index}",
                kind=product_kind,
                unit=product_unit,
                dtype=product_dtype,
                axes=product_axes,
                metadata={"definition": index},
            )
            for index in range(product_count)
        )
    )
    selected_products = (
        (products[0],) * product_count if shared_product and product_count else products
    )
    selections = tuple(
        record_product(product, record_id=f"record-{index}")
        for index, product in enumerate(selected_products)
    )
    uses = tuple(use for use, _record in selections)
    records = tuple(record for _use, record in selections)
    if records:
        records = (
            *records,
            RecordUse(
                id="alias-of-first-use",
                product_use_id=records[0].product_use_id,
                metadata={"projection": "alias"},
            ),
        )
    program = TypedProgram(
        id=f"domain-mapping-{point_count}-{product_count}",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows([{"x": float(index)} for index in range(point_count)]),
                    expected_type=point_type,
                )
            )
        ),
        product_defs=products,
        product_uses=uses,
        record_uses=records,
    )
    linked = link_program(
        program,
        validate_config_environment(load_config()),
    )
    return materialize_linked_points(linked)


def _valid_mapping_inputs(
    linked_points: MaterializedLinkedPoints,
    *,
    adapter_point_order: Sequence[int] = (2, 0, 1),
) -> tuple[
    tuple[AdapterEntryResults[str, str], ...],
    tuple[EntryPointBinding[str], ...],
    tuple[ResultUseBinding[str, str], ...],
]:
    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    entries = tuple(
        AdapterEntryResults(
            f"entry-{point_index}",
            tuple(
                f"result-{point_index}-{use_index}"
                for use_index in reversed(range(len(uses)))
            ),
        )
        for point_index in adapter_point_order
    )
    entry_bindings = tuple(
        EntryPointBinding(f"entry-{point_index}", points[point_index].logical_id)
        for point_index in reversed(tuple(adapter_point_order))
    )
    result_bindings = tuple(
        ResultUseBinding(
            f"entry-{point_index}",
            f"result-{point_index}-{use_index}",
            uses[use_index].id,
        )
        for point_index in reversed(tuple(adapter_point_order))
        for use_index in range(len(uses))
    )
    return entries, entry_bindings, result_bindings


def _all_product_use_ids(
    linked_points: MaterializedLinkedPoints,
) -> tuple[ProductUseId, ...]:
    return tuple(use.id for use in linked_points.linked_plan.product_uses)


def test_result_mapping_closes_reordered_adapter_work_to_logical_outputs() -> None:
    linked_points = _linked_points()
    adapter_entries, entry_bindings, result_bindings = _valid_mapping_inputs(
        linked_points
    )

    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        adapter_entries,
        entry_bindings,
        result_bindings,
    )

    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    assert mapping.selected_product_use_ids == tuple(use.id for use in uses)
    assert tuple(entry.entry_address for entry in mapping.adapter_entries) == (
        "entry-2",
        "entry-0",
        "entry-1",
    )
    assert tuple(entry.entry_address for entry in mapping.entries) == (
        "entry-0",
        "entry-1",
        "entry-2",
    )
    assert tuple(
        (result.logical_point_id, use_id)
        for result in mapping.results
        for use_id in result.product_use_ids
    ) == tuple((point.logical_id, use.id) for point in points for use in uses)
    assert len(mapping.results) == len(points) * len(uses)
    assert len(linked_points.linked_plan.record_uses) == len(uses) + 1

    selected = mapping.result_for_address("result-2-1")
    assert selected is mapping.result_for_output(points[2].logical_id, uses[1].id)
    assert selected is mapping.entry_for_address("entry-2").results[1]
    assert selected.product_uses == (uses[1],)
    assert selected.product_use_ids == (uses[1].id,)
    assert selected.product_id == uses[1].product_id
    assert selected.product.id == uses[1].product_id
    assert mapping.entry_for_point(points[2].logical_id).entry_address == "entry-2"

    exposed_product = selected.product
    exposed_product.metadata["mutated"] = True
    assert "mutated" not in selected.product.metadata

    with pytest.raises(ValueError, match="exactly cover adapter entries"):
        ClosedDomainResultMapping(
            mapping.linked_points,
            mapping.selected_product_use_ids,
            (),
            mapping.entries,
            mapping.results,
        )


def test_result_mapping_closes_only_the_selected_linked_point_batch() -> None:
    linked_points = _linked_points(point_count=4, product_count=1)
    batch = MaterializedLinkedPointBatch(linked_points, (1, 2))
    use = linked_points.linked_plan.product_uses[0]
    first, second = batch.point_domain.points

    mapping = seal_domain_result_mapping(
        batch,
        (use.id,),
        (
            AdapterEntryResults("entry-2", ("result-2",)),
            AdapterEntryResults("entry-1", ("result-1",)),
        ),
        (
            EntryPointBinding("entry-2", second.logical_id),
            EntryPointBinding("entry-1", first.logical_id),
        ),
        (
            ResultUseBinding("entry-2", "result-2", use.id),
            ResultUseBinding("entry-1", "result-1", use.id),
        ),
    )

    assert mapping.linked_points is batch
    assert tuple(entry.point for entry in mapping.entries) == (first, second)
    assert tuple(result.logical_point_id for result in mapping.results) == (
        linked_points.point_domain.points[1].logical_id,
        linked_points.point_domain.points[2].logical_id,
    )
    assert tuple(result.result_address for result in mapping.results) == (
        "result-1",
        "result-2",
    )


def test_result_mapping_canonicalizes_an_explicit_product_use_subset() -> None:
    linked_points = _linked_points(point_count=3, product_count=3)
    uses = linked_points.linked_plan.product_uses
    entries, entry_bindings, result_bindings = _valid_mapping_inputs(linked_points)
    selected_ids = (uses[2].id, uses[0].id)
    selected_set = set(selected_ids)
    selected_bindings = tuple(
        binding for binding in result_bindings if binding.product_use_id in selected_set
    )
    selected_addresses = {binding.result_address for binding in selected_bindings}
    selected_entries = tuple(
        AdapterEntryResults(
            entry.entry_address,
            tuple(
                result_address
                for result_address in entry.result_addresses
                if result_address in selected_addresses
            ),
        )
        for entry in entries
    )

    mapping = seal_domain_result_mapping(
        linked_points,
        selected_ids,
        selected_entries,
        entry_bindings,
        selected_bindings,
    )

    canonical_ids = (uses[0].id, uses[2].id)
    assert mapping.selected_product_use_ids == canonical_ids
    assert tuple(
        (result.logical_point_id, use_id)
        for result in mapping.results
        for use_id in result.product_use_ids
    ) == tuple(
        (point.logical_id, product_use_id)
        for point in linked_points.point_domain.points
        for product_use_id in canonical_ids
    )
    assert all(
        tuple(use_id for result in entry.results for use_id in result.product_use_ids)
        == canonical_ids
        for entry in mapping.entries
    )
    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.result_for_output(
            linked_points.point_domain.points[0].logical_id,
            uses[1].id,
        )


@pytest.mark.parametrize("selection", ["duplicate", "foreign", "wrong_type"])
def test_result_mapping_rejects_invalid_selected_product_uses(
    selection: str,
) -> None:
    linked_points = _linked_points()
    uses = linked_points.linked_plan.product_uses
    entries, entry_bindings, result_bindings = _valid_mapping_inputs(linked_points)
    if selection == "duplicate":
        selected_ids = (uses[0].id, uses[0].id)
        error_type = ValueError
        message = "must be unique"
    elif selection == "foreign":
        selected_ids = (uses[0].id, ProductUseId("foreign-use"))
        error_type = ValueError
        message = "not in the linked plan"
    else:
        selected_ids = cast(
            "tuple[ProductUseId, ...]",
            (uses[0].id, "not-a-product-use-id"),
        )
        error_type = TypeError
        message = "ProductUseId"

    with pytest.raises(error_type, match=message):
        seal_domain_result_mapping(
            linked_points,
            selected_ids,
            entries,
            entry_bindings,
            result_bindings,
        )


def test_result_mapping_rejects_results_for_unselected_product_uses() -> None:
    linked_points = _linked_points()
    uses = linked_points.linked_plan.product_uses

    with pytest.raises(ValueError, match="unselected product use"):
        seal_domain_result_mapping(
            linked_points,
            (uses[0].id,),
            *_valid_mapping_inputs(linked_points),
        )


def test_zero_point_mapping_retains_and_checks_selected_product_contracts() -> None:
    linked_points = _linked_points(
        point_count=0,
        product_count=1,
        product_kind="readback",
    )
    use = linked_points.linked_plan.product_uses[0]
    mapping = seal_domain_result_mapping(
        linked_points,
        (use.id,),
        (),
        (),
        (),
    )

    assert mapping.selected_product_use_ids == (use.id,)
    assert mapping.entries == ()
    assert mapping.results == ()
    with pytest.raises(CheckFailed) as captured:
        select_domain_measurement_outputs(mapping)
    assert {problem.code for problem in captured.value.problems} == {
        "domain_output_product_kind_unsupported"
    }
    with pytest.raises(CheckFailed) as direct:
        SelectedDomainMeasurementOutputs(mapping)
    assert {problem.code for problem in direct.value.problems} == {
        "domain_output_product_kind_unsupported"
    }


def test_empty_result_contract_fingerprint_covers_use_subset_and_entry_mapping() -> (
    None
):
    zero_points = _linked_points(point_count=0, product_count=2)
    uses = zero_points.linked_plan.product_uses
    first_mapping = seal_domain_result_mapping(
        zero_points,
        (uses[0].id,),
        (),
        (),
        (),
    )
    second_mapping = seal_domain_result_mapping(
        zero_points,
        (uses[1].id,),
        (),
        (),
        (),
    )

    def fingerprint(mapping: ClosedDomainResultMapping[str, str]) -> str:
        return close_domain_invocation(
            mapping,
            invocation_id="empty-contract",
            target_id="target",
            compiler_id="compiler",
            capability_fingerprint="capability",
            artifact_id="artifact",
            artifact_fingerprint="artifact-fingerprint",
            adapter_intent={"kind": "empty"},
            payload=None,
        ).intent.result_contract_fingerprint

    assert fingerprint(first_mapping) != fingerprint(second_mapping)

    points = _linked_points(point_count=1, product_count=1)
    point = points.point_domain.points[0]
    mapping_a = seal_domain_result_mapping(
        points,
        (),
        (AdapterEntryResults("entry-a"),),
        (EntryPointBinding("entry-a", point.logical_id),),
        (),
    )
    mapping_b = seal_domain_result_mapping(
        points,
        (),
        (AdapterEntryResults("entry-b"),),
        (EntryPointBinding("entry-b", point.logical_id),),
        (),
    )
    assert fingerprint(mapping_a) != fingerprint(mapping_b)


def test_mapping_snapshots_selected_product_contracts_for_invocation_identity() -> None:
    linked_points = _linked_points(point_count=0, product_count=1)
    use = linked_points.linked_plan.product_uses[0]
    mapping = seal_domain_result_mapping(
        linked_points,
        (use.id,),
        (),
        (),
        (),
    )

    def fingerprint() -> str:
        return close_domain_invocation(
            mapping,
            invocation_id="snapshotted-contract",
            target_id="target",
            compiler_id="compiler",
            capability_fingerprint="capability",
            artifact_id="artifact",
            artifact_fingerprint="artifact-fingerprint",
            adapter_intent={"kind": "empty"},
            payload=None,
        ).intent.result_contract_fingerprint

    before = mapping.contract_fingerprint
    assert fingerprint() == before
    linked_points.linked_plan.program.product_defs[0].metadata["mutated"] = True
    exposed = mapping.product_for_use(use.id)
    exposed.metadata["also-mutated"] = True

    assert mapping.contract_fingerprint == before
    assert fingerprint() == before
    retained = mapping.product_for_use(use.id)
    assert "mutated" not in retained.metadata
    assert "also-mutated" not in retained.metadata


@given(
    adapter_point_order=st.permutations((0, 1, 2)),
    entry_binding_order=st.permutations((0, 1, 2)),
    result_binding_order=st.permutations((0, 1, 2, 3, 4, 5)),
)
@settings(max_examples=30)
def test_adapter_and_binding_order_do_not_change_logical_output_order(
    adapter_point_order: list[int],
    entry_binding_order: list[int],
    result_binding_order: list[int],
) -> None:
    linked_points = _linked_points()
    entries, entry_bindings, result_bindings = _valid_mapping_inputs(
        linked_points,
        adapter_point_order=adapter_point_order,
    )
    selected_entry_bindings = tuple(
        entry_bindings[index] for index in entry_binding_order
    )
    selected_result_bindings = tuple(
        result_bindings[index] for index in result_binding_order
    )

    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        entries,
        selected_entry_bindings,
        selected_result_bindings,
    )

    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    assert tuple(
        (result.logical_point_id, use_id)
        for result in mapping.results
        for use_id in result.product_use_ids
    ) == tuple((point.logical_id, use.id) for point in points for use in uses)


def test_output_values_close_reordered_candidates_to_exact_logical_results() -> None:
    linked_points = _linked_points()
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points),
    )
    candidates = tuple(
        DomainOutputValue(
            result.result_address,
            Quantity(value=float(index), unit="ratio"),
        )
        for index, result in reversed(tuple(enumerate(mapping.results)))
    )
    selection = select_domain_measurement_outputs(mapping)

    closed = seal_domain_output_values(selection, candidates)

    assert closed.selection is selection
    assert closed.mapping is mapping
    assert tuple(output.result for output in closed.outputs) == mapping.results
    assert tuple(output.result_address for output in closed.outputs) == tuple(
        result.result_address for result in mapping.results
    )
    for index, output in enumerate(closed.outputs):
        assert closed.output_for_address(output.result_address) is output
        assert all(
            closed.output_for_output(output.logical_point_id, use_id) is output
            for use_id in output.product_use_ids
        )
        assert output.entry_address == output.result.entry_address
        assert output.product_id == output.result.product_id
        assert output.product == output.result.product
        assert output.value == Quantity(value=float(index), unit="ratio")
        assert output.value is not candidates[len(candidates) - index - 1].value


@given(candidate_order=st.permutations((0, 1, 2, 3, 4, 5)))
@settings(max_examples=30)
def test_output_candidate_order_does_not_change_logical_value_order(
    candidate_order: list[int],
) -> None:
    linked_points = _linked_points()
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points),
    )
    candidates = tuple(
        DomainOutputValue(
            result.result_address,
            Quantity(value=float(index), unit="ratio"),
        )
        for index, result in enumerate(mapping.results)
    )
    selection = select_domain_measurement_outputs(mapping)

    closed = seal_domain_output_values(
        selection,
        tuple(candidates[index] for index in candidate_order),
    )

    assert tuple(output.result_address for output in closed.outputs) == tuple(
        result.result_address for result in mapping.results
    )
    assert tuple(
        cast("Quantity", output.value).value for output in closed.outputs
    ) == tuple(float(index) for index in range(len(mapping.results)))


def test_closed_output_values_snapshot_mutable_measurement_arrays() -> None:
    linked_points = _linked_points(
        point_count=1,
        product_count=1,
        product_dtype="complex128",
        product_axes=(shot_axis(2),),
    )
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )
    source = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[2],
        values=[
            ComplexQuantity(real=1.0, imag=2.0, unit="ratio"),
            ComplexQuantity(real=3.0, imag=4.0, unit="ratio"),
        ],
    )
    selection = select_domain_measurement_outputs(mapping)

    closed = seal_domain_output_values(
        selection,
        (DomainOutputValue(mapping.results[0].result_address, source),),
    )
    source.values.clear()
    exposed = cast("MeasurementArray", closed.outputs[0].value)
    exposed.values.clear()

    retained = cast("MeasurementArray", closed.outputs[0].value)
    assert retained.shape == [2]
    assert retained.values == [
        ComplexQuantity(real=1.0, imag=2.0, unit="ratio"),
        ComplexQuantity(real=3.0, imag=4.0, unit="ratio"),
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_codes"),
    (
        ("missing", {"domain_output_missing_result"}),
        ("duplicate", {"domain_output_duplicate_result"}),
        ("unexpected", {"domain_output_unexpected_result"}),
    ),
)
def test_output_value_sealing_rejects_inexact_result_coverage(
    mutation: str,
    expected_codes: set[str],
) -> None:
    linked_points = _linked_points(point_count=1, product_count=1)
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )
    candidate = DomainOutputValue(
        mapping.results[0].result_address,
        Quantity(value=1.0, unit="ratio"),
    )
    selection = select_domain_measurement_outputs(mapping)
    if mutation == "missing":
        candidates = ()
    elif mutation == "duplicate":
        candidates = (candidate, candidate)
    else:
        candidates = (candidate, DomainOutputValue("foreign", candidate.value))

    with pytest.raises(ProviderContractError) as captured:
        seal_domain_output_values(selection, candidates)

    assert expected_codes.issubset(
        {problem.code for problem in captured.value.problems}
    )
    assert all(
        problem.phase.value == "execution" for problem in captured.value.problems
    )


@pytest.mark.parametrize(
    ("value", "expected_code"),
    (
        (
            MeasurementArray(
                dtype="bool",
                unit="ratio",
                shape=[2],
                values=[True, False],
            ),
            "domain_output_dtype_mismatch",
        ),
        (
            MeasurementArray(
                dtype="complex128",
                unit="arb",
                shape=[2],
                values=[
                    ComplexQuantity(real=1.0, imag=2.0, unit="arb"),
                    ComplexQuantity(real=3.0, imag=4.0, unit="arb"),
                ],
            ),
            "domain_output_unit_mismatch",
        ),
        (
            MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[1],
                values=[ComplexQuantity(real=1.0, imag=2.0, unit="ratio")],
            ),
            "domain_output_shape_mismatch",
        ),
        (
            MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[2],
                values=[complex(1.0, 2.0), complex(3.0, 4.0)],
            ),
            "domain_output_value_mismatch",
        ),
        (
            MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[2],
                values=[
                    ComplexQuantity(real=1.0, imag=2.0, unit="arb"),
                    ComplexQuantity(real=3.0, imag=4.0, unit="ratio"),
                ],
            ),
            "domain_output_value_mismatch",
        ),
    ),
)
def test_output_value_sealing_rejects_product_contract_mismatches(
    value: MeasurementArray,
    expected_code: str,
) -> None:
    linked_points = _linked_points(
        point_count=1,
        product_count=1,
        product_dtype="complex128",
        product_axes=(shot_axis(2),),
    )
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )
    selection = select_domain_measurement_outputs(mapping)

    with pytest.raises(ProviderContractError) as captured:
        seal_domain_output_values(
            selection,
            (DomainOutputValue(mapping.results[0].result_address, value),),
        )

    assert expected_code in {problem.code for problem in captured.value.problems}


def test_output_value_sealing_revalidates_mutated_measurement_models() -> None:
    linked_points = _linked_points(
        point_count=1,
        product_count=1,
        product_dtype="complex128",
    )
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )
    value = ComplexQuantity(real=1.0, imag=2.0, unit="ratio")
    object.__setattr__(value, "real", "not-a-number")
    selection = select_domain_measurement_outputs(mapping)

    with pytest.raises(ProviderContractError) as captured:
        seal_domain_output_values(
            selection,
            (DomainOutputValue(mapping.results[0].result_address, value),),
        )

    assert {problem.code for problem in captured.value.problems} == {
        "domain_output_value_mismatch"
    }
    assert captured.value.problems[0].details["contract_issue"] == (
        "value_model_invalid"
    )


@pytest.mark.parametrize(
    ("product_kind", "product_dtype", "product_unit", "expected_code"),
    (
        (
            "readback",
            "float64",
            "ratio",
            "domain_output_product_kind_unsupported",
        ),
        (
            "observable",
            "bool",
            None,
            "domain_output_scalar_dtype_unsupported",
        ),
        (
            "observable",
            "string",
            None,
            "domain_output_scalar_dtype_unsupported",
        ),
    ),
)
def test_output_value_selection_rejects_unsupported_measurement_carriers(
    product_kind: ProductKind,
    product_dtype: MeasurementDType,
    product_unit: str | None,
    expected_code: str,
) -> None:
    linked_points = _linked_points(
        point_count=1,
        product_count=1,
        product_kind=product_kind,
        product_dtype=product_dtype,
        product_unit=product_unit,
    )
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )

    with pytest.raises(CheckFailed) as captured:
        select_domain_measurement_outputs(mapping)

    assert expected_code in {problem.code for problem in captured.value.problems}
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


def test_output_value_sealing_accepts_axis_bearing_bool_arrays() -> None:
    linked_points = _linked_points(
        point_count=1,
        product_count=1,
        product_dtype="bool",
        product_unit=None,
        product_axes=(shot_axis(2),),
    )
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points, adapter_point_order=(0,)),
    )
    selection = select_domain_measurement_outputs(mapping)

    closed = seal_domain_output_values(
        selection,
        (
            DomainOutputValue(
                mapping.results[0].result_address,
                MeasurementArray(
                    dtype="bool",
                    shape=[2],
                    values=[True, False],
                ),
            ),
        ),
    )

    assert cast("MeasurementArray", closed.outputs[0].value).values == [True, False]


def test_mapping_supports_control_only_entries_without_fabricated_results() -> None:
    linked_points = _linked_points(point_count=2, product_count=2)
    points = linked_points.point_domain.points

    mapping = seal_domain_result_mapping(
        linked_points,
        (),
        (
            AdapterEntryResults("second"),
            AdapterEntryResults("first"),
        ),
        (
            EntryPointBinding("first", points[0].logical_id),
            EntryPointBinding("second", points[1].logical_id),
        ),
        (),
    )

    assert tuple(entry.entry_address for entry in mapping.entries) == (
        "first",
        "second",
    )
    assert mapping.selected_product_use_ids == ()
    assert all(entry.results == () for entry in mapping.entries)
    assert mapping.results == ()
    selection = select_domain_measurement_outputs(mapping)
    assert seal_domain_output_values(selection, ()).outputs == ()


def test_one_physical_result_fans_out_to_distinct_uses_of_one_product() -> None:
    linked_points = _linked_points(
        point_count=2,
        product_count=2,
        shared_product=True,
    )
    points = linked_points.point_domain.points
    uses = linked_points.linked_plan.product_uses
    assert uses[0].product_id == uses[1].product_id
    assert uses[0].id != uses[1].id

    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        (
            AdapterEntryResults("entry-1", ("result-1",)),
            AdapterEntryResults("entry-0", ("result-0",)),
        ),
        (
            EntryPointBinding("entry-1", points[1].logical_id),
            EntryPointBinding("entry-0", points[0].logical_id),
        ),
        tuple(
            ResultUseBinding(
                f"entry-{point.logical_ordinal}",
                f"result-{point.logical_ordinal}",
                use.id,
            )
            for point in reversed(points)
            for use in reversed(uses)
        ),
    )

    assert len(mapping.results) == len(points)
    assert all(
        result.product_uses == uses
        and result.product_use_ids == tuple(use.id for use in uses)
        for result in mapping.results
    )
    for point, result in zip(points, mapping.results, strict=True):
        assert mapping.result_for_output(point.logical_id, uses[0].id) is result
        assert mapping.result_for_output(point.logical_id, uses[1].id) is result

    selection = select_domain_measurement_outputs(mapping)
    closed = seal_domain_output_values(
        selection,
        tuple(
            DomainOutputValue(
                result.result_address,
                Quantity(value=float(index), unit="ratio"),
            )
            for index, result in enumerate(mapping.results)
        ),
    )

    assert len(closed.outputs) == len(points)
    for point, output in zip(points, closed.outputs, strict=True):
        assert closed.output_for_output(point.logical_id, uses[0].id) is output
        assert closed.output_for_output(point.logical_id, uses[1].id) is output


def test_fanout_rejects_mixed_products_and_split_product_results() -> None:
    distinct = _linked_points(point_count=1, product_count=2)
    point = distinct.point_domain.points[0]
    first_use, second_use = distinct.linked_plan.product_uses
    with pytest.raises(ValueError, match="only within one logical product result"):
        seal_domain_result_mapping(
            distinct,
            (first_use.id, second_use.id),
            (AdapterEntryResults("entry", ("result",)),),
            (EntryPointBinding("entry", point.logical_id),),
            (
                ResultUseBinding("entry", "result", first_use.id),
                ResultUseBinding("entry", "result", second_use.id),
            ),
        )

    shared = _linked_points(point_count=1, product_count=2, shared_product=True)
    shared_point = shared.point_domain.points[0]
    shared_uses = shared.linked_plan.product_uses
    with pytest.raises(ValueError, match="cannot be split across addresses"):
        seal_domain_result_mapping(
            shared,
            tuple(use.id for use in shared_uses),
            (AdapterEntryResults("entry", ("first", "second")),),
            (EntryPointBinding("entry", shared_point.logical_id),),
            (
                ResultUseBinding("entry", "first", shared_uses[0].id),
                ResultUseBinding("entry", "second", shared_uses[1].id),
            ),
        )


def test_fanout_rejects_a_duplicate_result_use_edge() -> None:
    linked_points = _linked_points(point_count=1, product_count=1)
    point = linked_points.point_domain.points[0]
    use = linked_points.linked_plan.product_uses[0]
    binding = ResultUseBinding("entry", "result", use.id)

    with pytest.raises(ValueError, match="unique result/product-use edges"):
        seal_domain_result_mapping(
            linked_points,
            (use.id,),
            (AdapterEntryResults("entry", ("result",)),),
            (EntryPointBinding("entry", point.logical_id),),
            (binding, binding),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing_entry", "exactly cover adapter entries"),
        ("duplicate_entry_point", "unique logical points"),
        ("foreign_point", "exactly cover materialized logical points"),
        ("missing_result", "exactly cover adapter result addresses"),
        ("foreign_result", "exactly cover adapter result addresses"),
        ("wrong_result_parent", "does not belong to its adapter entry"),
        ("unknown_use", "unknown product use"),
        ("duplicate_output", "map each logical point/product use once"),
    ),
)
def test_mapping_rejects_incomplete_or_foreign_edges_before_any_effect(
    mutation: str,
    message: str,
) -> None:
    linked_points = _linked_points()
    entries, entry_bindings, result_bindings = _valid_mapping_inputs(linked_points)

    if mutation == "missing_entry":
        entry_bindings = entry_bindings[:-1]
    elif mutation == "duplicate_entry_point":
        entry_bindings = (
            entry_bindings[0],
            EntryPointBinding(
                entry_bindings[1].entry_address,
                entry_bindings[0].logical_point_id,
            ),
            entry_bindings[2],
        )
    elif mutation == "foreign_point":
        foreign = _linked_points(point_count=4).point_domain.points[0].logical_id
        entry_bindings = (
            EntryPointBinding(entry_bindings[0].entry_address, foreign),
            *entry_bindings[1:],
        )
    elif mutation == "missing_result":
        result_bindings = result_bindings[:-1]
    elif mutation == "foreign_result":
        result_bindings = (
            ResultUseBinding(
                result_bindings[0].entry_address,
                "foreign-result",
                result_bindings[0].product_use_id,
            ),
            *result_bindings[1:],
        )
    elif mutation == "wrong_result_parent":
        result_bindings = (
            ResultUseBinding(
                "entry-0",
                result_bindings[0].result_address,
                result_bindings[0].product_use_id,
            ),
            *result_bindings[1:],
        )
    elif mutation == "unknown_use":
        result_bindings = (
            ResultUseBinding(
                result_bindings[0].entry_address,
                result_bindings[0].result_address,
                ProductUseId("foreign-use"),
            ),
            *result_bindings[1:],
        )
    elif mutation == "duplicate_output":
        result_bindings = (
            result_bindings[0],
            ResultUseBinding(
                result_bindings[1].entry_address,
                result_bindings[1].result_address,
                result_bindings[0].product_use_id,
            ),
            *result_bindings[2:],
        )

    with pytest.raises(ValueError, match=message):
        seal_domain_result_mapping(
            linked_points,
            _all_product_use_ids(linked_points),
            entries,
            entry_bindings,
            result_bindings,
        )


def test_mapping_rejects_duplicate_adapter_identity_inventory() -> None:
    linked_points = _linked_points()
    entries, entry_bindings, result_bindings = _valid_mapping_inputs(linked_points)

    with pytest.raises(ValueError, match="entry addresses must be unique"):
        seal_domain_result_mapping(
            linked_points,
            _all_product_use_ids(linked_points),
            (entries[0], entries[0], entries[2]),
            entry_bindings,
            result_bindings,
        )

    duplicated_result_entries = (
        entries[0],
        AdapterEntryResults(
            entries[1].entry_address,
            (entries[0].result_addresses[0], *entries[1].result_addresses[1:]),
        ),
        entries[2],
    )
    with pytest.raises(ValueError, match="result addresses must be globally unique"):
        seal_domain_result_mapping(
            linked_points,
            _all_product_use_ids(linked_points),
            duplicated_result_entries,
            entry_bindings,
            result_bindings,
        )


def test_mapping_inputs_require_hashable_nominal_addresses() -> None:
    with pytest.raises(TypeError, match="entry address must be hashable"):
        AdapterEntryResults(cast("str", []))
    with pytest.raises(TypeError, match="result address must be hashable"):
        AdapterEntryResults("entry", cast("tuple[str, ...]", ([],)))


def test_domain_output_candidates_require_typed_values_and_hashable_addresses() -> None:
    with pytest.raises(TypeError, match="result address must be hashable"):
        DomainOutputValue(cast("str", []), Quantity(value=1.0, unit="ratio"))
    with pytest.raises(TypeError, match="MeasurementValue"):
        DomainOutputValue("result", cast("Quantity", object()))


def test_mapping_lookups_reject_foreign_addresses_and_outputs() -> None:
    linked_points = _linked_points()
    mapping = seal_domain_result_mapping(
        linked_points,
        _all_product_use_ids(linked_points),
        *_valid_mapping_inputs(linked_points),
    )
    foreign_points = _linked_points(point_count=4)

    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.entry_for_address("foreign-entry")
    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.entry_for_point(foreign_points.point_domain.points[0].logical_id)
    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.result_for_address("foreign-result")
    with pytest.raises(KeyError, match="not in this mapping"):
        mapping.result_for_output(
            linked_points.point_domain.points[0].logical_id,
            ProductUseId("foreign-use"),
        )
