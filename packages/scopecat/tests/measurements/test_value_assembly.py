from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
)
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    ProductValueFragmentDef,
    assemble_measurement_values,
    bind_domain_output_fragment,
    domain_output_fragment,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.invocation import (
    AdapterEntryResults,
    DomainOutputValue,
    EntryPointBinding,
    ResultUseBinding,
    materialize_linked_points,
    seal_domain_output_values,
    seal_domain_result_mapping,
    select_domain_measurement_outputs,
)
from tests.testkit.measurement_assembly import (
    measurement_assembly_scenario,
    measurement_fragment_definition,
    measurement_value_candidates,
    select_measurement_assembly,
)


def test_assembly_selection_accepts_a_linked_point_batch() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0, 2.0), use_count=1)
    batch = MaterializedLinkedPointBatch(scenario.linked_points, (1, 2))

    selected = select_measurement_value_assembly(
        batch,
        required_product_use_ids=(scenario.uses[0].id,),
        fragment_defs=(measurement_fragment_definition("batch-values", scenario.uses),),
    )

    assert selected.linked_points is batch
    assert selected.linked_contract_fingerprint != (
        select_measurement_value_assembly(
            scenario.linked_points,
            required_product_use_ids=(scenario.uses[0].id,),
            fragment_defs=(
                measurement_fragment_definition("batch-values", scenario.uses),
            ),
        ).linked_contract_fingerprint
    )


@pytest.mark.parametrize(
    "definitions",
    (
        lambda uses: (
            measurement_fragment_definition("first", (uses[0],)),
            measurement_fragment_definition("overlap", (uses[0], uses[1])),
        ),
        lambda uses: (measurement_fragment_definition("missing", (uses[0],)),),
        lambda uses: (
            measurement_fragment_definition("duplicate", (uses[0],)),
            measurement_fragment_definition("duplicate", (uses[1],)),
        ),
    ),
    ids=("overlap", "missing", "duplicate-fragment-id"),
)
def test_assembly_selection_rejects_non_exact_fragment_ownership_before_values(
    definitions,
) -> None:
    scenario = measurement_assembly_scenario(use_count=2)

    with pytest.raises(CheckFailed):
        select_measurement_assembly(scenario, definitions(scenario.uses))


def test_assembly_selection_rejects_foreign_product_use_before_values() -> None:
    scenario = measurement_assembly_scenario(use_count=1)
    foreign = ProductValueFragmentDef(
        id="foreign",
        product_use_ids=(ProductUseId("foreign-use"),),
    )

    with pytest.raises(CheckFailed):
        select_measurement_value_assembly(
            scenario.linked_points,
            required_product_use_ids=(scenario.uses[0].id,),
            fragment_defs=(foreign,),
        )


def test_assembly_selection_rejects_duplicate_required_or_fragment_use() -> None:
    scenario = measurement_assembly_scenario(use_count=1)
    use_id = scenario.uses[0].id

    with pytest.raises(CheckFailed):
        select_measurement_value_assembly(
            scenario.linked_points,
            required_product_use_ids=(use_id, use_id),
            fragment_defs=(
                ProductValueFragmentDef(
                    id="duplicate-use",
                    product_use_ids=(use_id, use_id),
                ),
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "foreign-point", "foreign-use"),
)
def test_fragment_sealing_rejects_non_exact_point_use_values(mutation: str) -> None:
    scenario = measurement_assembly_scenario(use_count=1)
    selection = select_measurement_assembly(
        scenario, (measurement_fragment_definition("domain", scenario.uses),)
    )
    candidates = list(measurement_value_candidates(scenario, scenario.uses))
    if mutation == "missing":
        candidates.pop()
    elif mutation == "duplicate":
        candidates.append(candidates[0])
    elif mutation == "foreign-point":
        foreign = measurement_assembly_scenario(point_values=(9.0,), use_count=1)
        candidates[0] = MeasurementValueCandidate(
            logical_point_id=foreign.linked_points.point_domain.points[0].logical_id,
            product_use_id=scenario.uses[0].id,
            value=candidates[0].value,
        )
    else:
        candidates[0] = MeasurementValueCandidate(
            logical_point_id=candidates[0].logical_point_id,
            product_use_id=ProductUseId("foreign-use"),
            value=candidates[0].value,
        )

    with pytest.raises(ProviderContractError):
        seal_measurement_value_fragment(
            selection,
            "domain",
            candidates,
        )


@given(candidate_order=st.permutations((0, 1, 2, 3, 4, 5)))
def test_fragment_and_candidate_order_do_not_change_canonical_assembly(
    candidate_order: list[int],
) -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    definitions = (
        measurement_fragment_definition("outer", (scenario.uses[0], scenario.uses[2])),
        measurement_fragment_definition("middle", (scenario.uses[1],)),
    )
    selection = select_measurement_assembly(scenario, tuple(reversed(definitions)))
    outer_candidates = measurement_value_candidates(
        scenario,
        (scenario.uses[0], scenario.uses[2]),
    )
    # Hypothesis generates a permutation of six positions, while this fragment
    # owns four values. Preserve a generated relative order without indexing
    # outside the fragment inventory.
    reordered = tuple(
        outer_candidates[index]
        for index in candidate_order
        if index < len(outer_candidates)
    )
    outer = seal_measurement_value_fragment(selection, "outer", reordered)
    middle = seal_measurement_value_fragment(
        selection,
        "middle",
        tuple(reversed(measurement_value_candidates(scenario, (scenario.uses[1],)))),
    )

    assembled = assemble_measurement_values(selection, (middle, outer))

    assert tuple(
        (value.logical_point_id, value.product_use_id) for value in assembled.values
    ) == tuple(
        (point.logical_id, use.id)
        for point in scenario.linked_points.point_domain.points
        for use in scenario.uses
    )


@given(
    owners=st.tuples(*(st.integers(min_value=0, max_value=3) for _ in range(4))),
    fragment_order=st.permutations((0, 1, 2, 3)),
    reverse_candidates=st.tuples(*(st.booleans() for _ in range(4))),
)
def test_arbitrary_use_partitions_have_one_canonical_assembly(
    owners: tuple[int, int, int, int],
    fragment_order: list[int],
    reverse_candidates: tuple[bool, bool, bool, bool],
) -> None:
    scenario = measurement_assembly_scenario(use_count=4)
    uses_by_owner = tuple(
        tuple(
            use
            for use_index, use in enumerate(scenario.uses)
            if owners[use_index] == owner
        )
        for owner in range(4)
    )
    definitions = tuple(
        measurement_fragment_definition(f"fragment-{owner}", owned_uses)
        for owner, owned_uses in enumerate(uses_by_owner)
    )
    selection = select_measurement_assembly(
        scenario,
        tuple(definitions[index] for index in reversed(range(4))),
    )
    fragments = []
    for owner, owned_uses in enumerate(uses_by_owner):
        candidates = measurement_value_candidates(scenario, owned_uses)
        fragments.append(
            seal_measurement_value_fragment(
                selection,
                f"fragment-{owner}",
                tuple(reversed(candidates))
                if reverse_candidates[owner]
                else candidates,
            )
        )

    assembled = assemble_measurement_values(
        selection,
        tuple(fragments[index] for index in fragment_order),
    )

    assert tuple(
        (value.logical_point_id, value.product_use_id) for value in assembled.values
    ) == tuple(
        (point.logical_id, use.id)
        for point in scenario.linked_points.point_domain.points
        for use in scenario.uses
    )


def test_equivalent_rematerialization_does_not_require_object_identity() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    equivalent_points = materialize_linked_points(scenario.linked_points.linked_plan)
    first = select_measurement_assembly(
        scenario, (measurement_fragment_definition("source", scenario.uses),)
    )
    equivalent = select_measurement_value_assembly(
        equivalent_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
        fragment_defs=(measurement_fragment_definition("source", scenario.uses),),
    )
    fragment = seal_measurement_value_fragment(
        equivalent,
        "source",
        measurement_value_candidates(scenario, scenario.uses),
    )

    assembled = assemble_measurement_values(first, (fragment,))

    assert len(assembled.values) == 2
    assert assembled.selection.linked_points is scenario.linked_points


def test_distinct_uses_of_one_product_remain_distinct_values() -> None:
    scenario = measurement_assembly_scenario(use_count=2, shared_product=True)
    selection = select_measurement_assembly(
        scenario, (measurement_fragment_definition("shared", scenario.uses),)
    )
    fragment = seal_measurement_value_fragment(
        selection,
        "shared",
        measurement_value_candidates(scenario, scenario.uses),
    )

    assembled = assemble_measurement_values(selection, (fragment,))

    assert scenario.uses[0].product_id == scenario.uses[1].product_id
    assert scenario.uses[0].id != scenario.uses[1].id
    assert len(assembled.values) == 4
    assert {
        value.product_use_id
        for value in assembled.values
        if value.logical_point_id
        == scenario.linked_points.point_domain.points[0].logical_id
    } == {scenario.uses[0].id, scenario.uses[1].id}


def test_runtime_assembly_rejects_missing_duplicate_and_unselected_fragments() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    selection = select_measurement_assembly(
        scenario,
        (
            measurement_fragment_definition("first", (scenario.uses[0],)),
            measurement_fragment_definition("second", (scenario.uses[1],)),
        ),
    )
    first = seal_measurement_value_fragment(
        selection,
        "first",
        measurement_value_candidates(scenario, (scenario.uses[0],)),
    )
    second = seal_measurement_value_fragment(
        selection,
        "second",
        measurement_value_candidates(scenario, (scenario.uses[1],)),
    )

    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first,))
    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first, first, second))

    foreign_selection = select_measurement_assembly(
        scenario,
        (measurement_fragment_definition("foreign", scenario.uses),),
    )
    foreign = seal_measurement_value_fragment(
        foreign_selection,
        "foreign",
        measurement_value_candidates(scenario, scenario.uses),
    )
    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first, second, foreign))


def test_fragment_sealing_rejects_measurement_contract_mismatch() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=1)
    selection = select_measurement_assembly(
        scenario, (measurement_fragment_definition("source", scenario.uses),)
    )
    point = scenario.linked_points.point_domain.points[0]

    with pytest.raises(ProviderContractError) as captured:
        seal_measurement_value_fragment(
            selection,
            "source",
            (
                MeasurementValueCandidate(
                    logical_point_id=point.logical_id,
                    product_use_id=scenario.uses[0].id,
                    value=Quantity(value=1.0, unit="s"),
                ),
            ),
        )

    assert captured.value.problems[0].code == "measurement_value_unit_mismatch"


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "foreign-owner"))
def test_assembly_rejects_missing_duplicate_or_foreign_fragments(
    mutation: str,
) -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    selection = select_measurement_assembly(
        scenario,
        (
            measurement_fragment_definition("first", (scenario.uses[0],)),
            measurement_fragment_definition("second", (scenario.uses[1],)),
        ),
    )
    first = seal_measurement_value_fragment(
        selection,
        "first",
        measurement_value_candidates(scenario, (scenario.uses[0],)),
    )
    second = seal_measurement_value_fragment(
        selection,
        "second",
        measurement_value_candidates(scenario, (scenario.uses[1],)),
    )
    if mutation == "missing":
        fragments = (first,)
    elif mutation == "duplicate":
        fragments = (first, first, second)
    else:
        foreign_scenario = measurement_assembly_scenario(use_count=1)
        foreign_selection = select_measurement_assembly(
            foreign_scenario,
            (measurement_fragment_definition("foreign", foreign_scenario.uses),),
        )
        foreign = seal_measurement_value_fragment(
            foreign_selection,
            "foreign",
            measurement_value_candidates(foreign_scenario, foreign_scenario.uses),
        )
        fragments = (first, foreign)

    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, fragments)


def test_domain_output_fragment_strips_adapter_addresses_from_host_values() -> None:
    scenario = measurement_assembly_scenario(use_count=2, shared_product=True)
    points = scenario.linked_points.point_domain.points
    adapter_entries = tuple(
        AdapterEntryResults(
            f"entry-{point.logical_ordinal}",
            (f"result-{point.logical_ordinal}",),
        )
        for point in reversed(points)
    )
    mapping = seal_domain_result_mapping(
        scenario.linked_points,
        tuple(use.id for use in scenario.uses),
        adapter_entries,
        tuple(
            EntryPointBinding(
                f"entry-{point.logical_ordinal}",
                point.logical_id,
            )
            for point in points
        ),
        tuple(
            ResultUseBinding(
                f"entry-{point.logical_ordinal}",
                f"result-{point.logical_ordinal}",
                use.id,
            )
            for point in points
            for use in scenario.uses
        ),
    )
    domain_selection = select_domain_measurement_outputs(mapping)
    mismatched_assembly = select_measurement_assembly(
        scenario,
        (
            measurement_fragment_definition("first", (scenario.uses[0],)),
            measurement_fragment_definition("second", (scenario.uses[1],)),
        ),
    )
    with pytest.raises(CheckFailed):
        bind_domain_output_fragment(
            mismatched_assembly,
            "first",
            domain_selection,
        )
    assembly = select_measurement_assembly(
        scenario, (measurement_fragment_definition("domain", scenario.uses),)
    )
    domain_binding = bind_domain_output_fragment(
        assembly,
        "domain",
        domain_selection,
    )
    outputs = seal_domain_output_values(
        domain_selection,
        tuple(
            DomainOutputValue(
                result.result_address,
                Quantity(value=float(index), unit="ratio"),
            )
            for index, result in enumerate(mapping.results)
        ),
    )

    fragment = domain_output_fragment(domain_binding, outputs)
    assembled = assemble_measurement_values(assembly, (fragment,))

    assert len(mapping.results) == len(points)
    assert len(outputs.outputs) == len(points)
    assert len(fragment.values) == len(points) * len(scenario.uses)
    assert len(assembled.values) == len(points) * len(scenario.uses)
    assert tuple(value.logical_point_id for value in assembled.values) == tuple(
        point.logical_id for point in points for _use in scenario.uses
    )
    for point in points:
        first = assembled.value_for_output(point.logical_id, scenario.uses[0].id)
        second = assembled.value_for_output(point.logical_id, scenario.uses[1].id)
        assert first.value == second.value


def test_fragment_snapshots_mutable_measurement_values() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=1)
    selection = select_measurement_assembly(
        scenario, (measurement_fragment_definition("source", scenario.uses),)
    )
    original = Quantity(value=1.5, unit="ratio")
    candidate = MeasurementValueCandidate(
        logical_point_id=scenario.linked_points.point_domain.points[0].logical_id,
        product_use_id=scenario.uses[0].id,
        value=original,
    )

    fragment = seal_measurement_value_fragment(
        selection,
        "source",
        (candidate,),
    )
    # Bypass the frozen public model API to simulate hostile/private mutation
    # after sealing; the closed fragment must retain its defensive snapshot.
    object.__setattr__(original, "value", 99.0)
    exposed_candidate_value = candidate.value
    assert isinstance(exposed_candidate_value, Quantity)
    assert exposed_candidate_value.value == 99.0

    assembled = assemble_measurement_values(selection, (fragment,))
    retained = assembled.values[0].value
    assert isinstance(retained, Quantity)
    assert retained.value == 1.5


def test_zero_point_and_empty_required_assemblies_retain_their_contracts() -> None:
    zero_points = measurement_assembly_scenario(point_values=(), use_count=1)
    zero_selection = select_measurement_assembly(
        zero_points,
        (measurement_fragment_definition("zero", zero_points.uses),),
    )
    zero_fragment = seal_measurement_value_fragment(
        zero_selection,
        "zero",
        (),
    )
    zero_assembled = assemble_measurement_values(zero_selection, (zero_fragment,))

    assert zero_assembled.values == ()
    assert zero_assembled.product_use_ids == (zero_points.uses[0].id,)

    empty = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=0)
    empty_selection = select_measurement_value_assembly(
        empty.linked_points,
        required_product_use_ids=(),
        fragment_defs=(),
    )
    empty_assembled = assemble_measurement_values(empty_selection, ())

    assert empty_assembled.values == ()
    assert empty_assembled.product_use_ids == ()
