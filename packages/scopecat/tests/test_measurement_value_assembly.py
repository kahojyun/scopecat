from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import MaterializedLinkedPoints, link_program
from scopecat._compiler.point_domain import (
    LogicalPointId,
    PointDomain,
)
from scopecat._compiler.program import TypedProgram, product_output
from scopecat._compiler.records import RecordUse
from scopecat._point_domain_algebra import point_rows
from scopecat._product_identity import ProductUse, ProductUseId, product_use
from scopecat._relations import literal_rows
from scopecat.domain_invocation import (
    AdapterEntryResults,
    DomainOutputValue,
    EntryPointBinding,
    ResultUseBinding,
    materialize_linked_points,
    seal_domain_output_values,
    seal_domain_result_mapping,
    select_domain_measurement_outputs,
)
from scopecat.errors import CheckFailed, ProviderContractError
from scopecat.measurement_values import (
    MeasurementValueCandidate,
    ProductValueFragmentDef,
    assemble_measurement_values,
    bind_domain_output_fragment,
    domain_output_fragment,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue
from scopecat.value_types import Float, Payload, Scalar, Table, TableColumn
from tests.support.authoring import load_config
from tests.support.relation_plans import table_value_expr


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    uses: tuple[ProductUse, ...]


def _scenario(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
    use_count: int = 3,
    shared_product: bool = False,
) -> _Scenario:
    point_type = Table(
        columns=(
            TableColumn("x", Scalar(Float())),
            TableColumn("opaque", Scalar(Payload("point-payload"))),
        ),
        min_rows=len(point_values),
        max_rows=len(point_values),
    )
    if shared_product and use_count:
        products = (
            product_output(
                "shared-signal",
                unit="ratio",
                dtype="float64",
                metadata={"definition": "shared"},
            ),
        )
        selected_products = products * use_count
    else:
        products = tuple(
            product_output(
                f"signal-{index}",
                unit="ratio",
                dtype="float64",
                metadata={"definition": index},
            )
            for index in range(use_count)
        )
        selected_products = products
    uses = tuple(product_use(product.id) for product in selected_products)
    records: list[RecordUse] = []
    if uses:
        records.extend(
            (
                RecordUse(
                    id="primary",
                    product_use_id=uses[0].id,
                    metadata={"projection": "primary"},
                ),
                RecordUse(
                    id="alias",
                    product_use_id=uses[0].id,
                    metadata={"projection": "alias"},
                ),
            )
        )
    if len(uses) > 1:
        records.append(
            RecordUse(
                id="secondary",
                product_use_id=uses[1].id,
                metadata={"projection": "secondary"},
            )
        )
    program = TypedProgram(
        id=f"measurement-assembly-{len(point_values)}-{use_count}",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows(
                        [
                            {
                                "x": value,
                                "opaque": PayloadValue(
                                    schema_id="point-payload",
                                    payload={"ordinal": index},
                                ),
                            }
                            for index, value in enumerate(point_values)
                        ]
                    ),
                    expected_type=point_type,
                )
            )
        ),
        product_defs=products,
        product_uses=uses,
        record_uses=tuple(records),
    )
    linked_points = materialize_linked_points(
        link_program(program, validate_config_environment(load_config()))
    )
    return _Scenario(linked_points=linked_points, uses=uses)


def _definition(
    fragment_id: str,
    uses: tuple[ProductUse, ...],
) -> ProductValueFragmentDef:
    return ProductValueFragmentDef(
        id=fragment_id,
        product_use_ids=tuple(use.id for use in uses),
    )


def _candidates(
    scenario: _Scenario,
    uses: tuple[ProductUse, ...],
) -> tuple[MeasurementValueCandidate, ...]:
    return tuple(
        MeasurementValueCandidate(
            logical_point_id=point.logical_id,
            product_use_id=use.id,
            value=Quantity(
                value=float(point.logical_ordinal * 100 + use_index),
                unit="ratio",
            ),
        )
        for point in scenario.linked_points.point_domain.points
        for use_index, use in enumerate(uses)
    )


def _select(
    scenario: _Scenario,
    definitions: tuple[ProductValueFragmentDef, ...],
    *,
    required_uses: tuple[ProductUse, ...] | None = None,
):
    selected_uses = scenario.uses if required_uses is None else required_uses
    return select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in selected_uses),
        fragment_defs=definitions,
    )


@pytest.mark.parametrize(
    "definitions",
    (
        lambda uses: (
            _definition("first", (uses[0],)),
            _definition("overlap", (uses[0], uses[1])),
        ),
        lambda uses: (_definition("missing", (uses[0],)),),
        lambda uses: (
            _definition("duplicate", (uses[0],)),
            _definition("duplicate", (uses[1],)),
        ),
    ),
    ids=("overlap", "missing", "duplicate-fragment-id"),
)
def test_assembly_selection_rejects_non_exact_fragment_ownership_before_values(
    definitions,
) -> None:
    scenario = _scenario(use_count=2)

    with pytest.raises(CheckFailed):
        _select(scenario, definitions(scenario.uses))


def test_assembly_selection_rejects_foreign_product_use_before_values() -> None:
    scenario = _scenario(use_count=1)
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
    scenario = _scenario(use_count=1)
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
    scenario = _scenario(use_count=1)
    selection = _select(scenario, (_definition("domain", scenario.uses),))
    candidates = list(_candidates(scenario, scenario.uses))
    if mutation == "missing":
        candidates.pop()
    elif mutation == "duplicate":
        candidates.append(candidates[0])
    elif mutation == "foreign-point":
        foreign = _scenario(point_values=(9.0,), use_count=1)
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
    scenario = _scenario(use_count=3)
    definitions = (
        _definition("outer", (scenario.uses[0], scenario.uses[2])),
        _definition("middle", (scenario.uses[1],)),
    )
    selection = _select(scenario, tuple(reversed(definitions)))
    outer_candidates = _candidates(
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
        tuple(reversed(_candidates(scenario, (scenario.uses[1],)))),
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
    scenario = _scenario(use_count=4)
    uses_by_owner = tuple(
        tuple(
            use
            for use_index, use in enumerate(scenario.uses)
            if owners[use_index] == owner
        )
        for owner in range(4)
    )
    definitions = tuple(
        _definition(f"fragment-{owner}", owned_uses)
        for owner, owned_uses in enumerate(uses_by_owner)
    )
    selection = _select(
        scenario,
        tuple(definitions[index] for index in reversed(range(4))),
    )
    fragments = []
    for owner, owned_uses in enumerate(uses_by_owner):
        candidates = _candidates(scenario, owned_uses)
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
    scenario = _scenario(point_values=(0.0,), use_count=2)
    equivalent_points = materialize_linked_points(scenario.linked_points.linked_plan)
    first = _select(scenario, (_definition("source", scenario.uses),))
    equivalent = select_measurement_value_assembly(
        equivalent_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
        fragment_defs=(_definition("source", scenario.uses),),
    )
    fragment = seal_measurement_value_fragment(
        equivalent,
        "source",
        _candidates(scenario, scenario.uses),
    )

    assembled = assemble_measurement_values(first, (fragment,))

    assert len(assembled.values) == 2
    assert assembled.selection.linked_points is scenario.linked_points


def test_distinct_uses_of_one_product_remain_distinct_values() -> None:
    scenario = _scenario(use_count=2, shared_product=True)
    selection = _select(scenario, (_definition("shared", scenario.uses),))
    fragment = seal_measurement_value_fragment(
        selection,
        "shared",
        _candidates(scenario, scenario.uses),
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
    scenario = _scenario(point_values=(0.0,), use_count=2)
    selection = _select(
        scenario,
        (
            _definition("first", (scenario.uses[0],)),
            _definition("second", (scenario.uses[1],)),
        ),
    )
    first = seal_measurement_value_fragment(
        selection,
        "first",
        _candidates(scenario, (scenario.uses[0],)),
    )
    second = seal_measurement_value_fragment(
        selection,
        "second",
        _candidates(scenario, (scenario.uses[1],)),
    )

    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first,))
    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first, first, second))

    foreign_selection = _select(
        scenario,
        (_definition("foreign", scenario.uses),),
    )
    foreign = seal_measurement_value_fragment(
        foreign_selection,
        "foreign",
        _candidates(scenario, scenario.uses),
    )
    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, (first, second, foreign))


def test_fragment_sealing_rejects_measurement_contract_mismatch() -> None:
    scenario = _scenario(point_values=(0.0,), use_count=1)
    selection = _select(scenario, (_definition("source", scenario.uses),))
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
    scenario = _scenario(use_count=2)
    selection = _select(
        scenario,
        (
            _definition("first", (scenario.uses[0],)),
            _definition("second", (scenario.uses[1],)),
        ),
    )
    first = seal_measurement_value_fragment(
        selection,
        "first",
        _candidates(scenario, (scenario.uses[0],)),
    )
    second = seal_measurement_value_fragment(
        selection,
        "second",
        _candidates(scenario, (scenario.uses[1],)),
    )
    if mutation == "missing":
        fragments = (first,)
    elif mutation == "duplicate":
        fragments = (first, first, second)
    else:
        foreign_scenario = _scenario(use_count=1)
        foreign_selection = _select(
            foreign_scenario,
            (_definition("foreign", foreign_scenario.uses),),
        )
        foreign = seal_measurement_value_fragment(
            foreign_selection,
            "foreign",
            _candidates(foreign_scenario, foreign_scenario.uses),
        )
        fragments = (first, foreign)

    with pytest.raises(ProviderContractError):
        assemble_measurement_values(selection, fragments)


def test_domain_output_fragment_strips_adapter_addresses_from_host_values() -> None:
    scenario = _scenario(use_count=2)
    points = scenario.linked_points.point_domain.points
    adapter_entries = tuple(
        AdapterEntryResults(
            f"entry-{point.logical_ordinal}",
            tuple(
                f"result-{point.logical_ordinal}-{use_index}"
                for use_index in range(len(scenario.uses))
            ),
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
                f"result-{point.logical_ordinal}-{use_index}",
                use.id,
            )
            for point in points
            for use_index, use in enumerate(scenario.uses)
        ),
    )
    domain_selection = select_domain_measurement_outputs(mapping)
    mismatched_assembly = _select(
        scenario,
        (
            _definition("first", (scenario.uses[0],)),
            _definition("second", (scenario.uses[1],)),
        ),
    )
    with pytest.raises(CheckFailed):
        bind_domain_output_fragment(
            mismatched_assembly,
            "first",
            domain_selection,
        )
    assembly = _select(scenario, (_definition("domain", scenario.uses),))
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

    assert len(assembled.values) == len(mapping.results)
    assert all(not hasattr(value, "result_address") for value in assembled.values)
    assert tuple(value.logical_point_id for value in assembled.values) == tuple(
        result.logical_point_id for result in mapping.results
    )


def test_fragment_snapshots_mutable_measurement_values() -> None:
    scenario = _scenario(point_values=(0.0,), use_count=1)
    selection = _select(scenario, (_definition("source", scenario.uses),))
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
    zero_points = _scenario(point_values=(), use_count=1)
    zero_selection = _select(
        zero_points,
        (_definition("zero", zero_points.uses),),
    )
    zero_fragment = seal_measurement_value_fragment(
        zero_selection,
        "zero",
        (),
    )
    zero_assembled = assemble_measurement_values(zero_selection, (zero_fragment,))

    assert zero_assembled.values == ()
    assert zero_assembled.product_use_ids == (zero_points.uses[0].id,)

    empty = _scenario(point_values=(0.0, 1.0), use_count=0)
    empty_selection = select_measurement_value_assembly(
        empty.linked_points,
        required_product_use_ids=(),
        fragment_defs=(),
    )
    empty_assembled = assemble_measurement_values(empty_selection, ())

    assert empty_assembled.values == ()
    assert empty_assembled.product_use_ids == ()


def test_candidate_requires_nominal_point_and_use_identity() -> None:
    scenario = _scenario(point_values=(0.0,), use_count=1)
    point = scenario.linked_points.point_domain.points[0]

    with pytest.raises(TypeError, match="LogicalPointId"):
        MeasurementValueCandidate(
            logical_point_id=point.logical_id.value,  # type: ignore[arg-type]
            product_use_id=scenario.uses[0].id,
            value=Quantity(value=1.0, unit="ratio"),
        )
    with pytest.raises(TypeError, match="ProductUseId"):
        MeasurementValueCandidate(
            logical_point_id=point.logical_id,
            product_use_id=scenario.uses[0].id.value,  # type: ignore[arg-type]
            value=Quantity(value=1.0, unit="ratio"),
        )
    assert isinstance(point.logical_id, LogicalPointId)
