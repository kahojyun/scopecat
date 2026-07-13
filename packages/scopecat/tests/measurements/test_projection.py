from __future__ import annotations

import pytest

from scopecat.compiler.linking.linked import MaterializedLinkedPointBatch
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.projection import (
    bind_measurement_projection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.values import (
    ProductValueFragmentDef,
    assemble_measurement_values,
    seal_measurement_value_fragment,
    select_measurement_value_assembly,
)
from scopecat.records.parameter import Quantity
from tests.testkit.measurement_assembly import (
    assembled_measurement_values_for_all_uses,
    measurement_assembly_scenario,
    measurement_fragment_definition,
    measurement_value_candidates,
)


def test_projection_selects_record_backed_uses_without_changing_assembly() -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    projection = select_measurement_projection(scenario.linked_points)

    assert projection.required_product_use_ids == (
        scenario.uses[0].id,
        scenario.uses[1].id,
    )
    assert scenario.uses[2].id not in projection.required_product_use_ids
    assert tuple(record.id for record in projection.records) == (
        "primary",
        "alias",
        "secondary",
    )


def test_projection_selects_only_the_linked_point_batch() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0, 2.0), use_count=2)
    batch = MaterializedLinkedPointBatch(scenario.linked_points, (1, 2))

    projection = select_measurement_projection(batch)

    assert projection.linked_points is batch
    assert projection.coordinate_ids == ("x",)
    assert projection.schema is not None
    assert (
        next(
            dimension
            for dimension in projection.schema.dimensions
            if dimension.id == "point"
        ).size
        == 2
    )


def test_explicit_record_subset_keeps_projection_separate_from_value_assembly() -> None:
    scenario, selected, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(
        scenario.linked_points,
        record_ids=("alias",),
    )
    bound = bind_measurement_projection(projection, selected)

    projected = project_measurement_records(
        bound,
        assembled,
        run_id="record-subset-run",
    )

    assert projection.required_product_use_ids == (scenario.uses[0].id,)
    assert len(assembled.values) == 6
    assert all(set(record.observables) == {"alias"} for record in projected.records)


def test_projection_binding_requires_every_record_backed_use_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    projection = select_measurement_projection(scenario.linked_points)
    incomplete = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(scenario.uses[0].id,),
        fragment_defs=(
            ProductValueFragmentDef(
                id="only-first",
                product_use_ids=(scenario.uses[0].id,),
            ),
        ),
    )

    with pytest.raises(CheckFailed):
        bind_measurement_projection(projection, incomplete)


def test_record_aliases_project_one_value_twice_without_expanding_assembly() -> None:
    scenario, selected, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.linked_points)
    bound = bind_measurement_projection(projection, selected)

    projected = project_measurement_records(
        bound,
        assembled,
        run_id="projection-run",
    )

    assert len(assembled.values) == len(scenario.linked_points.point_domain.points) * 3
    assert len(projected.records) == 2
    assert [record.point_index for record in projected.records] == [0, 1]
    for record in projected.records:
        assert set(record.observables) == {"primary", "alias", "secondary"}
        assert record.observables["primary"] == record.observables["alias"]


def test_projection_filters_non_coordinate_point_values() -> None:
    scenario, selected, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.linked_points)
    bound = bind_measurement_projection(projection, selected)

    projected = project_measurement_records(
        bound,
        assembled,
        run_id="coordinate-filter-run",
    )

    assert [record.coordinates for record in projected.records] == [
        {"x": 0.0},
        {"x": 1.0},
    ]
    assert all("opaque" not in record.coordinates for record in projected.records)


def test_record_metadata_changes_schema_not_product_value_assembly() -> None:
    scenario, selected, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.linked_points)
    bound = bind_measurement_projection(projection, selected)
    projected = project_measurement_records(
        bound,
        assembled,
        run_id="record-metadata-run",
    )

    assert len(assembled.values) == 6
    first_value = assembled.values[0]
    assert first_value.product.metadata == {"definition": 0}
    assert "projection" not in first_value.product.metadata
    assert projected.schema is not None
    variables = {variable.id: variable for variable in projected.schema.variables}
    assert variables["primary"].metadata == {
        "definition": 0,
        "projection": "primary",
    }
    assert variables["alias"].metadata == {
        "definition": 0,
        "projection": "alias",
    }


def test_duplicate_coordinate_rows_keep_distinct_canonical_point_indices() -> None:
    scenario, selected, assembled = assembled_measurement_values_for_all_uses(
        point_values=(4.0, 4.0)
    )
    projection = select_measurement_projection(scenario.linked_points)
    bound = bind_measurement_projection(projection, selected)

    projected = project_measurement_records(
        bound,
        assembled,
        run_id="duplicate-coordinate-run",
    )

    assert [record.point_index for record in projected.records] == [0, 1]
    assert [record.coordinates for record in projected.records] == [
        {"x": 4.0},
        {"x": 4.0},
    ]
    assert (
        scenario.linked_points.point_domain.points[0].logical_id
        != scenario.linked_points.point_domain.points[1].logical_id
    )


def test_projection_snapshots_values_and_emits_complete_run_records() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    definition = measurement_fragment_definition("source", scenario.uses)
    selected = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
        fragment_defs=(definition,),
    )
    candidates = list(measurement_value_candidates(scenario, scenario.uses))
    fragment = seal_measurement_value_fragment(
        selected,
        "source",
        candidates,
    )
    exposed_candidate_value = candidates[0].value
    assert isinstance(exposed_candidate_value, Quantity)
    # Simulate mutation below the frozen public API after the fragment copied it.
    object.__setattr__(exposed_candidate_value, "value", 999.0)
    assembled = assemble_measurement_values(selected, (fragment,))
    bound = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        selected,
    )

    projected = project_measurement_records(
        bound,
        assembled,
        run_id="complete-record-run",
    )

    assert len(projected.records) == 1
    record = projected.records[0]
    assert record.run_id == "complete-record-run"
    assert record.point_index == 0
    assert record.coordinates == {"x": 0.0}
    primary = record.observables["primary"]
    assert isinstance(primary, Quantity)
    assert primary.value == 0.0

    object.__setattr__(primary, "value", 777.0)
    retained_primary = projected.records[0].observables["primary"]
    assert isinstance(retained_primary, Quantity)
    assert retained_primary.value == 0.0


def test_zero_points_and_no_record_projection_produce_no_measurement_records() -> None:
    zero = measurement_assembly_scenario(point_values=(), use_count=1)
    zero_projection = select_measurement_projection(zero.linked_points)
    zero_selected = select_measurement_value_assembly(
        zero.linked_points,
        required_product_use_ids=(zero.uses[0].id,),
        fragment_defs=(measurement_fragment_definition("zero", zero.uses),),
    )
    zero_fragment = seal_measurement_value_fragment(
        zero_selected,
        "zero",
        (),
    )
    zero_values = assemble_measurement_values(zero_selected, (zero_fragment,))
    zero_bound = bind_measurement_projection(zero_projection, zero_selected)

    assert (
        project_measurement_records(
            zero_bound,
            zero_values,
            run_id="zero-run",
        ).records
        == ()
    )

    no_records = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=0)
    empty_projection = select_measurement_projection(no_records.linked_points)
    empty_selected = select_measurement_value_assembly(
        no_records.linked_points,
        required_product_use_ids=(),
        fragment_defs=(),
    )
    empty_values = assemble_measurement_values(empty_selected, ())
    empty_bound = bind_measurement_projection(empty_projection, empty_selected)

    assert (
        project_measurement_records(
            empty_bound,
            empty_values,
            run_id="no-record-run",
        ).records
        == ()
    )


def test_projected_recording_contract_matches_bound_projection() -> None:
    _scenario_value, selected, assembled = assembled_measurement_values_for_all_uses()
    bound = bind_measurement_projection(
        select_measurement_projection(_scenario_value.linked_points),
        selected,
    )

    first = project_measurement_records(bound, assembled, run_id="stable-record-run")
    assert first.recording_contract_fingerprint == bound.contract_fingerprint
