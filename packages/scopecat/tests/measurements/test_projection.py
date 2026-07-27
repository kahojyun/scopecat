from __future__ import annotations

from scopecat.compiler.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.projection import (
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.values import (
    seal_measurement_values,
)
from tests.testkit.measurement_assembly import (
    assembled_measurement_values_for_all_uses,
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def test_projection_keeps_all_records_without_narrowing_the_value_catalog() -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    assert projection.catalog.product_use_ids == tuple(use.id for use in scenario.uses)
    assert tuple(record.id for record in projection.records) == (
        "primary",
        "alias",
        "secondary",
    )


def test_projection_selects_only_the_linked_point_batch() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0, 1.0, 2.0), use_count=2)
    complete_projection = select_measurement_projection(
        scenario.catalog,
        scenario.records,
    )
    catalog = project_measurement_catalog(scenario.linked_points, (1, 2))
    projection = select_measurement_projection(catalog, scenario.records)

    selected_points = project_run_point_catalog(scenario.linked_points, (1, 2)).points
    ordinals = tuple(point.ordinal for point in selected_points)
    assert ordinals == (1, 2)
    assert projection.coordinate_ids == ("x",)
    assert (
        projection.catalog.contract_fingerprint
        == complete_projection.catalog.contract_fingerprint
    )
    assert projection.contract_fingerprint == complete_projection.contract_fingerprint
    schema = projection.schema_for(selected_points)
    assert schema is not None
    assert (
        next(
            dimension for dimension in schema.dimensions if dimension.id == "point"
        ).size
        == 2
    )


def test_record_aliases_project_one_value_twice_without_expanding_assembly() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="projection-run",
        points=scenario.points,
    )

    assert len(assembled.values) == len(scenario.linked_points.point_domain.points) * 3
    assert len(projected.records) == 2
    assert [record.point_index for record in projected.records] == [0, 1]
    for record in projected.records:
        assert set(record.observables) == {"primary", "alias", "secondary"}
        assert record.observables["primary"] == record.observables["alias"]


def test_projection_filters_non_coordinate_point_values() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="coordinate-filter-run",
        points=scenario.points,
    )

    assert [record.coordinates for record in projected.records] == [
        {"x": 0.0},
        {"x": 1.0},
    ]
    assert all("opaque" not in record.coordinates for record in projected.records)


def test_record_metadata_changes_schema_not_product_value_assembly() -> None:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    projected = project_measurement_records(
        projection,
        assembled,
        run_id="record-metadata-run",
        points=scenario.points,
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
    scenario, assembled = assembled_measurement_values_for_all_uses(
        point_values=(4.0, 4.0)
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="duplicate-coordinate-run",
        points=scenario.points,
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


def test_projection_emits_complete_run_records() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)
    assembled = seal_measurement_values(
        scenario.catalog,
        measurement_value_candidates(scenario, scenario.uses),
        points=scenario.points,
    )
    projection = select_measurement_projection(scenario.catalog, scenario.records)

    projected = project_measurement_records(
        projection,
        assembled,
        run_id="complete-record-run",
        points=scenario.points,
    )

    assert len(projected.records) == 1
    record = projected.records[0]
    assert record.run_id == "complete-record-run"
    assert record.point_index == 0
    assert record.coordinates == {"x": 0.0}
    primary = record.observables["primary"]
    assert isinstance(primary, Quantity)
    assert primary.value == 0.0


def test_zero_points_and_no_record_projection_produce_no_measurement_records() -> None:
    zero = measurement_assembly_scenario(point_values=(), use_count=1)
    zero_values = seal_measurement_values(
        zero.catalog,
        (),
        points=zero.points,
    )
    zero_projection = select_measurement_projection(zero.catalog, zero.records)

    assert (
        project_measurement_records(
            zero_projection,
            zero_values,
            run_id="zero-run",
            points=zero.points,
        ).records
        == ()
    )

    no_records = measurement_assembly_scenario(point_values=(0.0, 1.0), use_count=0)
    empty_values = seal_measurement_values(
        no_records.catalog,
        (),
        points=no_records.points,
    )
    empty_projection = select_measurement_projection(
        no_records.catalog, no_records.records
    )

    assert (
        project_measurement_records(
            empty_projection,
            empty_values,
            run_id="no-record-run",
            points=no_records.points,
        ).records
        == ()
    )


def test_projected_recording_contract_matches_bound_projection() -> None:
    _scenario_value, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(
        _scenario_value.catalog, _scenario_value.records
    )

    first = project_measurement_records(
        projection,
        assembled,
        run_id="stable-record-run",
        points=_scenario_value.points,
    )
    assert first.recording_contract_fingerprint == projection.contract_fingerprint
